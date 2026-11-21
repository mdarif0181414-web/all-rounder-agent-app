# All-Rounder Agent — Stage 7 web app (Streamlit, free stack)।
# Key শুধু env/secrets থেকে আসে; code-এ কখনো নয় (A3)।
import os
import time

import streamlit as st

# Secrets → env (core import-এর আগে হতে হবে)
try:
    for k in ("GEMINI_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_KEY"):
        if k in st.secrets and not os.environ.get(k):
            os.environ[k] = str(st.secrets[k])
except Exception:
    pass
os.environ.setdefault("STAGE2_APPROVAL", "deny")

st.set_page_config(page_title="All-Rounder Agent", page_icon="🤖",
                   layout="wide")

try:  # Neon P2: product theme + welcome screen (ব্যর্থ হলেও app চলবে)
    from ui.theme import apply_pro_theme, render_empty_welcome_screen
    apply_pro_theme()
except Exception:
    render_empty_welcome_screen = None

try:  # Neon P1: live production trace renderer
    from ui.agent_trace import (ProductionTraceRenderer,
                                render_saved_trace, render_studio_result)
except Exception:
    ProductionTraceRenderer = None
    render_saved_trace = None
    render_studio_result = None

try:  # Neon P3: persistent chat history (Supabase)
    from chat_store import get_cached_chat_store
    from ui.chat_sidebar import (refresh_sessions_cache,
                                 render_chat_sidebar)
except Exception:
    get_cached_chat_store = None
    render_chat_sidebar = None
    refresh_sessions_cache = None

try:  # Neon P4: split-screen workspace panel
    from ui.workspace import (extract_chat_artifact, render_chat_workspace,
                              render_studio_workspace)
except Exception:
    extract_chat_artifact = None
    render_chat_workspace = None
    render_studio_workspace = None

try:  # Neon P5: brain switcher + smart input + feedback bar
    from ui.controls import (build_augmented_prompt, parse_chat_submission,
                             process_uploaded_files, render_brain_switcher,
                             render_feedback_bar, render_smart_chat_input,
                             resolve_model_chain)
except Exception:
    build_augmented_prompt = None
    parse_chat_submission = None
    process_uploaded_files = None
    render_brain_switcher = None
    render_feedback_bar = None
    render_smart_chat_input = None
    resolve_model_chain = None

try:  # Neon P6: access gate + health + dual-lane lesson recall
    from ui.auth import (get_current_user_id, render_logout_button,
                         require_access_gate)
    from ui.health import cleanup_temp_media, render_health_popover
    from lesson_recall import (build_system_prompt_with_lessons,
                               get_cached_lessons, invalidate_lessons_cache)
except Exception:
    get_current_user_id = None
    render_logout_button = None
    require_access_gate = None
    cleanup_temp_media = None
    render_health_popover = None
    build_system_prompt_with_lessons = None
    get_cached_lessons = None
    invalidate_lessons_cache = None

try:  # Neon Stage 2.2: 24/7 job queue (Mission Control)
    from job_store import JobStore
except Exception:
    JobStore = None

# Neon P6: PIN সেট থাকলে app এখানেই লক — st.stop() swallow করা যাবে না,
# তাই এই call-এ try/except নেই (নিরাপত্তা)।
if require_access_gate is not None:
    require_access_gate()

if (cleanup_temp_media is not None
        and not st.session_state.get("_tmp_cleaned")):
    try:
        cleanup_temp_media(max_age_minutes=30)
    except Exception:
        pass
    st.session_state["_tmp_cleaned"] = True

current_uid = "owner"
if get_current_user_id is not None:
    try:
        current_uid = get_current_user_id()
    except Exception:
        current_uid = "owner"

try:
    import agent_app_core as core
    CORE_ERR = None
except Exception as e:
    core = None
    CORE_ERR = f"{type(e).__name__}: {e}"

st.title("🤖 All-Rounder Agent")
st.caption("তোমার নিজের autonomous agent — chat, video production, memory। "
           "Development version (streaming chat)")

if CORE_ERR:
    st.error(f"Agent core চালু হয়নি: {CORE_ERR}")
    st.info("GEMINI_API_KEY secret/env ঠিকমতো set আছে কিনা দেখো।")
    st.stop()


def _remember_with_cache_bust(content, source="FEEDBACK"):
    """Feedback lesson সেভ + Dual-Lane lesson cache invalidate (P6)।"""
    result = core.remember_fact(content, source)
    if invalidate_lessons_cache is not None:
        try:
            invalidate_lessons_cache()
        except Exception:
            pass
    return result


remember_fn = (_remember_with_cache_bust
               if core is not None and hasattr(core, "remember_fact")
               else None)

stats = core.memory_stats()
with st.sidebar:
    st.subheader("Agent-এর অবস্থা")
    st.write(f"🧠 Memory: **{stats['count']}**টি ({stats['backend']})")
    try:
        import playwright  # noqa: F401
        st.write("🌐 Browser tools: **আছে**")
    except Exception:
        st.write("🌐 Browser tools: **নেই** (এই environment-এ research "
                 "ছাড়া বাকি সব চলবে)")
    st.write("🔑 Brain: Gemini (free tier)")

chat_store = None
if get_cached_chat_store is not None and render_chat_sidebar is not None:
    try:
        chat_store = get_cached_chat_store()
        render_chat_sidebar(chat_store, messages_key="history",
                            user_id=current_uid)
    except Exception:
        chat_store = None


def persist_turn_safely(user_prompt, assistant_reply, elapsed_sec):
    """উত্তর শেষ হওয়ার পর Supabase-এ নীরবে সেভ — ব্যর্থ হলেও chat
    ভাঙে না (Neon P3: lazy session creation, hybrid cache)।
    ফেরত দেয় assistant message-এর DB id (feedback PATCH-এর জন্য)।"""
    if chat_store is None or not chat_store.is_configured():
        return None
    try:
        sid = st.session_state.get("active_session_id")
        created_new = False
        if not sid:
            new_sess = chat_store.create_session(title=user_prompt,
                                                 user_id=current_uid)
            if new_sess:
                sid = new_sess["id"]
                st.session_state["active_session_id"] = sid
                created_new = True
        if sid:
            chat_store.append_message(sid, "user", user_prompt)
            row = chat_store.append_message(
                sid, "assistant", assistant_reply,
                meta={"elapsed_sec": round(float(elapsed_sec), 2)})
            if refresh_sessions_cache and (
                    created_new
                    or st.session_state.get("chat_sessions_cache")
                    is not None):
                refresh_sessions_cache(chat_store, user_id=current_uid)
            return (row or {}).get("id")
    except Exception as exc:
        st.toast(f"হিস্ট্রি সেভ হয়নি (লোকালি আছে): {exc}", icon="⚠️")
    return None


brain_mode = "auto"
if render_brain_switcher is not None:
    try:
        with st.sidebar:
            st.divider()
            st.caption("🧠 উত্তরের ধরন (Brain)")
            brain_mode = render_brain_switcher()
    except Exception:
        brain_mode = "auto"

if render_health_popover is not None:
    try:
        with st.sidebar:
            st.divider()
            render_health_popover(
                list(core.CHAT_MODELS) if core is not None else [])
            if render_logout_button is not None:
                render_logout_button()
    except Exception:
        pass


tab_chat, tab_studio, tab_mem = st.tabs(
    ["💬 Chat", "🎬 Production Studio", "🧠 Memory"])

with tab_chat:
    if "history" not in st.session_state:
        st.session_state.history = []
    # Neon P4: artifact থাকলেই কেবল split — নইলে chat full width
    has_art = (render_chat_workspace is not None
               and bool(st.session_state.get("chat_active_artifact")))
    if has_art:
        col_chat, col_ws = st.columns([1.1, 0.95], gap="medium")
    else:
        col_chat, col_ws = st.container(), None
    with col_chat:
        starter = None
        if not st.session_state.history and render_empty_welcome_screen:
            starter = render_empty_welcome_screen()
        for idx, msg in enumerate(st.session_state.history):
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                meta = msg.get("meta") or {}
                for att in (meta.get("attachments_meta") or []):
                    st.caption(f"📎 {att.get('name', '')} "
                               f"({att.get('size_kb', '?')} KB)")
                if msg["role"] == "assistant":
                    if meta.get("elapsed_sec") is not None:
                        st.caption(
                            f"⚡ {meta['elapsed_sec']} সেকেন্ডে উত্তর তৈরি")
                    if extract_chat_artifact is not None:
                        detected = extract_chat_artifact(msg["content"])
                        if detected and st.button(
                                "🧩 Workspace-এ দেখুন",
                                key=f"open_chat_art_{idx}"):
                            st.session_state["chat_active_artifact"] = \
                                detected
                            st.rerun()
                    if render_feedback_bar is not None:
                        prev_q = ""
                        if (idx > 0 and st.session_state.history[idx - 1]
                                ["role"] == "user"):
                            prev_q = (st.session_state.history[idx - 1]
                                      ["content"])
                        render_feedback_bar(
                            idx, msg, prev_q, chat_store,
                            remember_fn=remember_fn)
        if render_smart_chat_input is not None:
            submission = render_smart_chat_input(
                "Agent-কে কিছু জিজ্ঞেস করো… বা ফাইল/ছবি যুক্ত করো")
            q, up_files = parse_chat_submission(submission)
        else:
            q = st.chat_input("Agent-কে কিছু জিজ্ঞেস করো…") or ""
            up_files = []
        if not q and starter:
            q = starter
        if q or up_files:
            bundle = (process_uploaded_files(up_files) if up_files else
                      {"context_text": "", "image_parts": [],
                       "attachments_meta": [], "warnings": []})
            for w in bundle["warnings"]:
                st.warning(w)
            model_q = (build_augmented_prompt(q, bundle)
                       if bundle["context_text"] else q)
            if not model_q.strip():
                model_q = ("সংযুক্ত ছবি/ফাইলটি বিশ্লেষণ করে মূল "
                           "বিষয়বস্তু বাংলায় বুঝিয়ে দিন।")
            display_q = q if q else "📎 সংযুক্ত ফাইল বিশ্লেষণ করো"
            st.session_state.history.append(
                {"role": "user", "content": display_q,
                 "meta": {"attachments_meta": bundle["attachments_meta"]}})
            with st.chat_message("user"):
                st.markdown(display_q)
                for att in bundle["attachments_meta"]:
                    st.caption(f"📎 {att.get('name', '')} "
                               f"({att.get('size_kb', '?')} KB)")
            with st.chat_message("assistant"):
                t0 = time.time()
                chain = None
                if resolve_model_chain is not None:
                    try:
                        chain = resolve_model_chain(
                            brain_mode, list(core.CHAT_MODELS))
                    except Exception:
                        chain = None
                images = bundle["image_parts"] or None
                sys_prompt = None
                if (build_system_prompt_with_lessons is not None
                        and get_cached_lessons is not None):
                    try:
                        sys_prompt = build_system_prompt_with_lessons(
                            core.CHAT_SYSTEM, get_cached_lessons(limit=5))
                    except Exception:
                        sys_prompt = None
                try:
                    if hasattr(core, "chat_answer_stream"):
                        try:
                            stream = core.chat_answer_stream(
                                model_q, models=chain, image_parts=images,
                                system_prompt=sys_prompt)
                        except TypeError:  # পুরনো core cache
                            stream = core.chat_answer_stream(model_q)
                        ans = st.write_stream(stream)
                    else:  # পুরনো core cache থাকলে chat ভাঙবে না
                        ans = core.chat_answer(model_q)
                        st.markdown(ans)
                except Exception as e:
                    ans = f"⚠️ উত্তর আসেনি: {type(e).__name__}: {e}"
                    st.markdown(ans)
                elapsed = round(time.time() - t0, 1)
                st.caption(f"⚡ {elapsed} সেকেন্ডে উত্তর তৈরি")
            st.session_state.history.append(
                {"role": "assistant", "content": ans,
                 "meta": {"elapsed_sec": elapsed,
                          "brain_mode": brain_mode},
                 "feedback": 0})
            msg_id = persist_turn_safely(display_q, ans, elapsed)
            if msg_id:
                st.session_state.history[-1]["id"] = msg_id
            if render_feedback_bar is not None:
                render_feedback_bar(
                    len(st.session_state.history) - 1,
                    st.session_state.history[-1], display_q, chat_store,
                    remember_fn=remember_fn)
    if col_ws is not None:
        with col_ws:
            render_chat_workspace()

with tab_studio:
    if (ProductionTraceRenderer is not None
            and render_studio_workspace is not None):
        # Neon P4: বামে control + live trace, ডানে workspace panel
        col_left, col_right = st.columns([1.0, 1.15], gap="medium")
        with col_right:
            live_preview_slot = st.empty()
        with col_left:
            st.write("একটা brief দাও — agent research করে পুরো faceless "
                     "video package বানিয়ে দেবে (৫টি deliverable)। "
                     "কাজের প্রতিটা ধাপ live দেখতে পাবে।")
            brief = st.text_area(
                "Brief",
                value="A small online education channel wants ONE 60–90 "
                      "second English faceless explainer video. Pick the "
                      "best topic from real YouTube evidence.",
                height=100, key="studio_brief")
            c_run, c_reset = st.columns([0.75, 0.25])
            run_clicked = c_run.button("🚀 Production চালাও",
                                       type="primary",
                                       use_container_width=True)
            if c_reset.button("🧹 রিসেট", use_container_width=True):
                st.session_state.pop("last_studio_trace", None)
                st.session_state.pop("last_studio_result", None)
                st.session_state.pop("studio_selected_item", None)
                st.rerun()
            if run_clicked and brief.strip():
                st.session_state.pop("studio_selected_item", None)
                renderer = ProductionTraceRenderer(
                    max_steps=30, live_preview_slot=live_preview_slot)
                try:
                    result = core.run_produce(
                        brief.strip(), on_event=renderer.handle_event)
                    trace = renderer.finalize(result, show_result=False)
                except Exception as e:
                    trace = renderer.fail(f"{type(e).__name__}: {e}")
                    result = None
                st.session_state["last_studio_trace"] = trace
                st.session_state["last_studio_result"] = result
            elif st.session_state.get("last_studio_result"):
                res = st.session_state["last_studio_result"]
                if render_saved_trace:
                    render_saved_trace(
                        st.session_state.get("last_studio_trace", []))
                if res.get("brain"):
                    st.caption(f"🧠 Brain: `{res['brain']}`")
                checks = res.get("checks") or {}
                if checks:
                    with st.expander("✅ Contract যাচাই (মাপা, agent-এর "
                                     "দাবি নয়)", expanded=True):
                        for cname, ok in checks.items():
                            st.markdown(
                                f"{'✅' if ok else '⚠️'} **{cname}**")
            # Neon Stage 2.2: 24/7 queue — brief কিউতে দিলে GitHub
            # Actions-এর বড় machine-এ নিজে নিজে চলবে
            if JobStore is not None:
                try:
                    _js = JobStore()
                except Exception:
                    _js = None
                if _js is not None and _js.is_configured():
                    st.divider()
                    c_tag, c_queue = st.columns([0.55, 0.45])
                    project_tag = c_tag.text_input(
                        "প্রজেক্ট / চ্যানেল ট্যাগ", value="general",
                        key="studio_project_tag",
                        label_visibility="collapsed",
                        placeholder="যেমন: yt_channel_1 বা fiverr_client")
                    if c_queue.button("⏳ 24/7 কিউতে দিন",
                                      key="btn_enqueue_247",
                                      use_container_width=True):
                        if not brief.strip():
                            st.warning("আগে একটি ব্রিফ লিখুন।")
                        else:
                            try:
                                created = _js.enqueue_job(
                                    brief=brief.strip(),
                                    project_tag=project_tag or "general",
                                    user_id=current_uid)
                                if created:
                                    st.success(
                                        "✅ 24/7 কিউতে যুক্ত হয়েছে "
                                        f"(`{created['id'][:8]}`) — পরের "
                                        "GitHub Actions রানে চলবে!")
                                else:
                                    st.warning("কিউতে দেওয়া যায়নি।")
                            except Exception as exc:
                                st.warning(
                                    "কিউ এখনো তৈরি নয় — Supabase-এ "
                                    f"agent_jobs টেবিল লাগবে ({exc})")
                    try:
                        _jobs = _js.list_jobs(user_id=current_uid, limit=8)
                    except Exception:
                        _jobs = None
                    if _jobs is not None:
                        with st.expander("🤖 24/7 Autonomous Queue "
                                         "স্ট্যাটাস", expanded=False):
                            if not _jobs:
                                st.caption("এখনো কোনো 24/7 জব কিউতে নেই।")
                            for j in _jobs:
                                icon = {"pending": "⏳",
                                        "running": "⚡",
                                        "completed": "✅",
                                        "failed": "❌"}.get(
                                            j["status"], "•")
                                line = (f"{icon} **[{j['project_tag']}]** "
                                        f"{j['brief'][:70]}")
                                if j.get("github_run_url"):
                                    line += (f" — [Run]"
                                             f"({j['github_run_url']})")
                                st.markdown(line)
                                if j.get("error_message"):
                                    st.caption(
                                        f"⚠️ {j['error_message'][:140]}")
        with col_right:
            live_preview_slot.empty()
            render_studio_workspace(
                st.session_state.get("last_studio_result"))
    else:  # split না হলে পুরনো single-column পথ (fallback)
        st.write("একটা brief দাও — agent research করে পুরো faceless video "
                 "package বানিয়ে দেবে (৫টি deliverable)। কাজের প্রতিটা ধাপ "
                 "live দেখতে পাবে।")
        brief = st.text_area(
            "Brief",
            value="A small online education channel wants ONE 60–90 second "
                  "English faceless explainer video. Pick the best topic "
                  "from real YouTube evidence.",
            height=100, key="studio_brief")
        if (st.button("🚀 Production চালাও", type="primary")
                and brief.strip()):
            if ProductionTraceRenderer is not None:
                renderer = ProductionTraceRenderer(max_steps=30)
                try:
                    result = core.run_produce(
                        brief.strip(), on_event=renderer.handle_event)
                    trace = renderer.finalize(result)
                except Exception as e:
                    trace = renderer.fail(f"{type(e).__name__}: {e}")
                    result = None
                st.session_state["last_studio_trace"] = trace
                st.session_state["last_studio_result"] = result
            else:
                log_box = st.empty()
                lines = []

                def log(msg):
                    lines.append(msg)
                    log_box.code("\n".join(lines[-12:]))

                with st.spinner("Agent কাজ করছে — কয়েক মিনিট লাগতে পারে…"):
                    try:
                        result = core.run_produce(brief, log=log)
                    except Exception as e:
                        result = None
                        st.error(f"Run ব্যর্থ: {type(e).__name__}: {e}")
                if result and render_studio_result:
                    render_studio_result(result)
                st.session_state["last_studio_result"] = result
                st.session_state["last_studio_trace"] = []
        elif st.session_state.get("last_studio_result"):
            if render_saved_trace:
                render_saved_trace(
                    st.session_state.get("last_studio_trace", []))
            if render_studio_result:
                render_studio_result(
                    st.session_state["last_studio_result"])

with tab_mem:
    st.write(f"মোট memory: **{stats['count']}**টি ({stats['backend']})")
    mq = st.text_input("Memory-তে খুঁজে দেখো", placeholder="যেমন: SmartToon")
    if mq:
        for r in core.recall(mq):
            st.markdown(f"- {r.get('content', '')}  \n"
                        f"  *সূত্র: {r.get('source', '')}*")

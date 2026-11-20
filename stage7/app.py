# All-Rounder Agent — Stage 7 web app (Streamlit, free stack)।
# Key শুধু env/secrets থেকে আসে; code-এ কখনো নয় (A3)।
import os

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
                   layout="centered")

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

tab_chat, tab_studio, tab_mem = st.tabs(
    ["💬 Chat", "🎬 Production Studio", "🧠 Memory"])

with tab_chat:
    if "history" not in st.session_state:
        st.session_state.history = []
    if st.button("🧹 Chat পরিষ্কার করো"):
        st.session_state.history = []
        st.rerun()
    for role, text in st.session_state.history:
        with st.chat_message(role):
            st.markdown(text)
    q = st.chat_input("Agent-কে কিছু জিজ্ঞেস করো…")
    if q:
        st.session_state.history.append(("user", q))
        with st.chat_message("user"):
            st.markdown(q)
        with st.chat_message("assistant"):
            try:
                ans = st.write_stream(core.chat_answer_stream(q))
            except Exception as e:
                ans = f"⚠️ উত্তর আসেনি: {type(e).__name__}: {e}"
                st.markdown(ans)
        st.session_state.history.append(("assistant", ans))

with tab_studio:
    st.write("একটা brief দাও — agent research করে পুরো faceless video "
             "package বানিয়ে দেবে (৫টি deliverable)।")
    brief = st.text_area(
        "Brief",
        value="A small online education channel wants ONE 60–90 second "
              "English faceless explainer video. Pick the best topic from "
              "real YouTube evidence.",
        height=100)
    if st.button("🚀 Production চালাও", type="primary"):
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
        if result:
            st.success(f"শেষ হয়েছে (brain: {result['brain']})")
            st.subheader("📋 Contract যাচাই (মাপা, agent-এর দাবি নয়)")
            for name, ok in result["checks"].items():
                st.write(("✅ " if ok else "⚠️ ") + name)
            st.subheader("📦 Deliverables")
            for fname, content in result["files"].items():
                with st.expander(f"📄 {fname}"):
                    st.markdown(content) if fname.endswith(".md") \
                        else st.code(content)
                    st.download_button(f"⬇️ {fname}", content,
                                       file_name=fname, key=f"dl-{fname}")
            if result["report"]:
                st.subheader("🏁 Agent-এর report")
                st.markdown(result["report"])

with tab_mem:
    st.write(f"মোট memory: **{stats['count']}**টি ({stats['backend']})")
    mq = st.text_input("Memory-তে খুঁজে দেখো", placeholder="যেমন: SmartToon")
    if mq:
        for r in core.recall(mq):
            st.markdown(f"- {r.get('content', '')}  \n"
                        f"  *সূত্র: {r.get('source', '')}*")

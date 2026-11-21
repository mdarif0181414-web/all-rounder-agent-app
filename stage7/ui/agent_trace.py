# Live Production trace renderer (Neon P1, 2026-11-20)।
# run_produce-এর structured events live দেখায়: progress bar, st.status
# box-এ ধাপে ধাপে tool trace, শেষে contract check + deliverables।
# finalize() trace_log ফেরত দেয় — P3-তে Supabase JSONB-তে সেভ হবে।
import time

import streamlit as st

try:  # Neon P4: ডান প্যানেলে live preview placeholder
    from ui.workspace import render_live_studio_placeholder
except Exception:
    render_live_studio_placeholder = None

_TOOL_ICONS = [
    (("youtube", "search", "research", "web"), "🔍"),
    (("browser", "playwright"), "🌐"),
    (("read",), "📄"),
    (("write", "append"), "📝"),
    (("measure",), "📏"),
    (("scan", "quality"), "🛡️"),
    (("preserve",), "🔒"),
    (("gate",), "✅"),
    (("lesson",), "🧠"),
    (("memory", "recall", "remember", "supabase"), "📚"),
    (("narration", "tts", "audio"), "🎙️"),
    (("video", "ffmpeg", "assemble", "image", "card"), "🎬"),
    (("file",), "📁"),
]


def get_tool_icon(tool_name: str) -> str:
    name = (tool_name or "").lower()
    for keys, icon in _TOOL_ICONS:
        if any(k in name for k in keys):
            return icon
    return "⚙️"


def _shorten(text, limit=140) -> str:
    s = str(text or "").strip().replace("\n", " ")
    return s if len(s) <= limit else s[:limit - 3] + "..."


class ProductionTraceRenderer:
    def __init__(self, max_steps: int = 30,
                 title: str = "⚡ এজেন্ট প্রোডাকশন মিশন চালাচ্ছে...",
                 live_preview_slot=None):
        self.max_steps = max_steps
        self.live_preview_slot = live_preview_slot
        self.start_time = time.perf_counter()
        self.trace_log = []
        self.tool_count = 0
        self.current_step = 0
        self.progress_bar = st.progress(
            0.0, text=f"ধাপ ০ / {max_steps} — শুরু হচ্ছে...")
        self.status_box = st.status(title, expanded=True)

    # --- event handling -------------------------------------------------
    def handle_event(self, event: dict) -> None:
        etype = event.get("type")
        if etype != "token":
            self.trace_log.append(event)
        self.current_step = max(self.current_step, event.get("step", 0))
        mx = event.get("max_steps", self.max_steps)
        ratio = min(0.95, max(0.02, self.current_step / max(mx, 1)))
        with self.status_box:
            if etype == "run_start":
                self.progress_bar.progress(
                    0.02, text=f"ধাপ ১ / {mx} — পরিকল্পনা তৈরি হচ্ছে...")
                st.caption("🎯 মিশন শুরু: "
                           + _shorten(event.get("brief", ""), 160))
            elif etype == "thought":
                self.progress_bar.progress(
                    ratio, text=f"ধাপ {self.current_step} / {mx} — ভাবছে...")
                st.markdown(f"💭 **ধাপ {self.current_step}:** "
                            f"*{_shorten(event.get('content', ''), 220)}*")
            elif etype == "tool_start":
                self.tool_count += 1
                tool = event.get("tool", "")
                icon = get_tool_icon(tool)
                self.progress_bar.progress(
                    ratio, text=f"ধাপ {self.current_step} / {mx} — "
                                f"{tool} চলছে...")
                st.markdown(f"{icon} **`{tool}`** চলছে... "
                            f"`{_shorten(event.get('args', ''), 110)}`")
            elif etype == "tool_end":
                tool = event.get("tool", "")
                icon = get_tool_icon(tool)
                dur = event.get("duration_sec")
                dur_txt = f" ({dur}s)" if dur is not None else ""
                st.caption(f"↳ {icon} `{tool}` সম্পন্ন{dur_txt}: "
                           f"{_shorten(event.get('summary', ''), 160)}")
                shot = event.get("screenshot_path")
                if shot:
                    st.image(shot, caption=f"Live View — {tool}",
                             use_container_width=True)
            elif etype == "tool_error":
                st.warning(f"⚠️ `{event.get('tool', '')}` এরর (এজেন্ট নিজে "
                           f"সমাধান খুঁজছে): "
                           f"{_shorten(event.get('error', ''), 160)}")
            elif etype == "gate_check":
                detail = _shorten(event.get("detail", ""), 160)
                name = event.get("check_name", "Quality / Preserve Gate")
                if event.get("passed"):
                    st.success(f"✅ Gate Pass — **{name}**: {detail}")
                else:
                    st.error(f"❌ Gate Fail — **{name}**: {detail}")
            elif etype == "deliverable":
                path = str(event.get("path", ""))
                st.caption(f"📦 ফাইল তৈরি হয়েছে: `{path.split('/')[-1]}`")
        if (self.live_preview_slot is not None
                and render_live_studio_placeholder is not None):
            try:
                render_live_studio_placeholder(self.live_preview_slot, event)
            except Exception:
                pass

    # --- completion -----------------------------------------------------
    def finalize(self, result: dict = None, show_result: bool = True) -> list:
        elapsed = round(time.perf_counter() - self.start_time, 1)
        self.progress_bar.progress(
            1.0, text=f"✅ সম্পন্ন — {self.tool_count}টি টুল • "
                      f"{elapsed} সেকেন্ড")
        self.status_box.update(
            label=f"✅ প্রোডাকশন সম্পন্ন ({self.current_step} ধাপ • "
                  f"{self.tool_count}টি টুল • {elapsed} সেকেন্ড)",
            state="complete", expanded=False)
        if result and show_result:
            render_studio_result(result)
        return self.trace_log

    def fail(self, error) -> list:
        elapsed = round(time.perf_counter() - self.start_time, 1)
        self.progress_bar.empty()
        self.status_box.update(
            label=f"❌ প্রোডাকশন থেমে গেছে ({elapsed} সেকেন্ড)",
            state="error", expanded=True)
        with self.status_box:
            st.error(f"এরর বিবরণ: {_shorten(error, 300)}")
        return self.trace_log


def render_studio_result(result: dict) -> None:
    """run_produce-এর ফলাফল (আমাদের আসল shape): brain, contract checks,
    deliverable files (expander + download), agent report।"""
    if not result:
        return
    st.success(f"শেষ হয়েছে (brain: {result.get('brain', '?')})")
    checks = result.get("checks") or {}
    if checks:
        st.subheader("📋 Contract যাচাই (মাপা, agent-এর দাবি নয়)")
        for name, ok in checks.items():
            st.write(("✅ " if ok else "⚠️ ") + name)
    files = result.get("files") or {}
    if files:
        st.subheader("📦 Deliverables")
        for fname, content in files.items():
            with st.expander(f"📄 {fname}"):
                if fname.endswith(".md"):
                    st.markdown(content)
                else:
                    st.code(content)
                st.download_button(f"⬇️ {fname}", content,
                                   file_name=fname, key=f"dl-{fname}")
    if result.get("report"):
        st.subheader("🏁 Agent-এর report")
        st.markdown(result["report"])


def render_saved_trace(trace_log: list) -> None:
    """পুরনো run-এর সংরক্ষিত trace — expander-এ ধাপগুলো (P3-ready)।"""
    if not trace_log:
        return
    tool_count = sum(1 for e in trace_log if e.get("type") == "tool_start")
    with st.expander(f"🔎 এজেন্টের কাজের ধাপ ({tool_count}টি টুল ব্যবহৃত)",
                     expanded=False):
        for e in trace_log:
            etype = e.get("type")
            if etype == "thought":
                st.caption(f"💭 ধাপ {e.get('step', '')}: "
                           f"{_shorten(e.get('content', ''), 200)}")
            elif etype == "tool_start":
                tool = e.get("tool", "")
                st.markdown(f"{get_tool_icon(tool)} **`{tool}`** "
                            f"`{_shorten(e.get('args', ''), 100)}`")
            elif etype == "tool_end":
                dur = e.get("duration_sec")
                dur_txt = f" ({dur}s)" if dur is not None else ""
                st.caption(f"↳ সম্পন্ন{dur_txt}: "
                           f"{_shorten(e.get('summary', ''), 140)}")
            elif etype == "gate_check":
                badge = "✅" if e.get("passed") else "❌"
                st.markdown(f"{badge} **{e.get('check_name', 'Gate')}**: "
                            f"{_shorten(e.get('detail', ''), 140)}")

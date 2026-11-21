# ui/workspace.py
import os
import re
from typing import Any, Dict, List, Optional, Tuple
import streamlit as st
import streamlit.components.v1 as components

# 1GB RAM (Streamlit Cloud Free Tier) সুরক্ষা সীমা
MAX_TEXT_PREVIEW_CHARS = 150_000      # ~150 KB টেক্সট/কোড প্রিভিউ লিমিট
MAX_MEDIA_PREVIEW_BYTES = 20 * 1024 * 1024  # 20 MB অডিও/ভিডিও/ইমেজ প্রিভিউ লিমিট

CODE_EXT_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".json": "json",
    ".sql": "sql",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".css": "css",
    ".sh": "bash",
    ".bash": "bash",
    ".xml": "xml",
    ".csv": "csv",
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a"}
VIDEO_EXTS = {".mp4", ".mov", ".webm"}
HTML_EXTS = {".html", ".htm"}
MARKDOWN_EXTS = {".md", ".markdown"}

_FENCED_CODE_RE = re.compile(r"```([a-zA-Z0-9_+-]*)\n(.*?)```", re.DOTALL)


def is_existing_file_path(value: Any) -> bool:
    """
    লিনাক্সে বড় স্ট্রিং বা নাল-বাইটে os.path.isfile() ক্র্যাশ আটকায়।
    """
    if not isinstance(value, str):
        return False
    if not value or "\n" in value or "\r" in value or "\x00" in value or len(value) > 512:
        return False
    try:
        return os.path.isfile(value)
    except OSError:
        return False


def detect_kind(filename: str) -> Tuple[str, str]:
    """ফাইলের নাম দেখে ধরন (markdown/code/html/image/audio/video/text) ও ভাষা বের করে।"""
    ext = os.path.splitext((filename or "").strip())[1].lower()
    if ext in MARKDOWN_EXTS:
        return "markdown", "markdown"
    if ext in HTML_EXTS:
        return "html", "html"
    if ext in IMAGE_EXTS:
        return "image", ""
    if ext in AUDIO_EXTS:
        return "audio", ""
    if ext in VIDEO_EXTS:
        return "video", ""
    if ext in CODE_EXT_LANG:
        return "code", CODE_EXT_LANG[ext]
    return "text", ""


def _read_download_bytes(content: Any) -> Optional[bytes]:
    """কেবল সিলেক্ট করা একটি ফাইলের জন্যই ডাউনলোড বাইটস তৈরি করে (RAM সাশ্রয়)।"""
    if content is None:
        return None
    if isinstance(content, bytes):
        return content
    if is_existing_file_path(content):
        size = os.path.getsize(content)
        if size > MAX_MEDIA_PREVIEW_BYTES:
            return None
        with open(content, "rb") as f:
            return f.read()
    return str(content).encode("utf-8")


def render_file_preview(name: str, content: Any, key_prefix: str = "ws") -> None:
    """
    যেকোনো deliverable (str, bytes, অথবা disk path) নিরাপদে ও RAM-সেফভাবে প্রিভিউ করে।
    """
    kind, lang = detect_kind(name)
    is_path = is_existing_file_path(content)

    # ফাইল পাথ হলে সাইজ চেক
    if is_path:
        file_size = os.path.getsize(content)
        if file_size > MAX_MEDIA_PREVIEW_BYTES:
            mb = round(file_size / (1024 * 1024), 1)
            st.warning(
                f"ফাইলটি বড় ({mb} MB) — ফ্রি ১ জিবি RAM সুরক্ষার জন্য ইনলাইন প্রিভিউ বন্ধ রাখা হয়েছে। "
                f"পাথ: `{content}`"
            )
            return

    # ১. ইমেজ / অডিও / ভিডিও প্রিভিউ
    if kind in ("image", "audio", "video"):
        if isinstance(content, bytes) and len(content) > MAX_MEDIA_PREVIEW_BYTES:
            st.warning("মিডিয়া ফাইলটি ২০ MB-এর বেশি; ইনলাইন প্রিভিউ এড়িয়ে যাওয়া হয়েছে।")
            return
        if not is_path and not isinstance(content, bytes):
            st.info("মিডিয়া প্রিভিউয়ের জন্য বৈধ ফাইল পাথ বা বাইনারি ডেটা পাওয়া যায়নি।")
            return

        if kind == "image":
            st.image(content, caption=name, use_container_width=True)
        elif kind == "audio":
            st.audio(content)
        elif kind == "video":
            st.video(content)
        return

    # ২. টেক্সট / কোড / মার্কডাউন / HTML লোড করা
    if is_path:
        with open(content, "r", encoding="utf-8", errors="replace") as f:
            text_data = f.read(MAX_TEXT_PREVIEW_CHARS + 1)
    elif isinstance(content, bytes):
        text_data = content[:MAX_TEXT_PREVIEW_CHARS].decode("utf-8", errors="replace")
    else:
        text_data = str(content or "")

    truncated = len(text_data) > MAX_TEXT_PREVIEW_CHARS
    if truncated:
        text_data = text_data[:MAX_TEXT_PREVIEW_CHARS]
        st.caption("⚠️ ফাইলটি অনেক বড় — দ্রুত রেন্ডারের জন্য প্রথম ১৫০ KB দেখানো হচ্ছে। সম্পূর্ণ পেতে ডাউনলোড করুন।")

    if kind == "markdown":
        t_prev, t_raw = st.tabs(["👁️ প্রিভিউ", "📝 Raw Markdown"])
        with t_prev:
            st.markdown(text_data)
        with t_raw:
            st.code(text_data, language="markdown")

    elif kind == "html":
        t_prev, t_src = st.tabs(["🌐 লাইভ HTML প্রিভিউ", "💻 সোর্স কোড"])
        with t_prev:
            components.html(text_data, height=460, scrolling=True)
        with t_src:
            st.code(text_data, language="html")

    elif kind == "code":
        st.code(text_data, language=lang)

    else:
        st.code(text_data, language="text")


def render_live_studio_placeholder(slot: Any, event: Dict[str, Any]) -> None:
    """
    Production Studio-র ৩০-স্টেপ রান চলাকালীন ডান প্যানেলে লাইভ স্ক্রিনশট বা নতুন ফাইল দেখায়।
    """
    if slot is None:
        return
    etype = event.get("type")
    if etype == "tool_end":
        shot = event.get("screenshot_path")
        if is_existing_file_path(shot):
            with slot.container(border=True):
                st.caption(f"🌐 লাইভ ব্রাউজার ভিউ — `{event.get('tool', 'browser')}` (ধাপ {event.get('step', 0)})")
                st.image(shot, use_container_width=True)
    elif etype == "deliverable":
        path = event.get("path", "")
        with slot.container(border=True):
            st.caption(f"📦 নতুন ডেলিভারেবল তৈরি হয়েছে: `{os.path.basename(str(path))}`")
            if is_existing_file_path(path):
                render_file_preview(os.path.basename(path), path, key_prefix="live_deliv")


@st.fragment
def render_studio_workspace(result: Optional[Dict[str, Any]]) -> None:
    """
    Production Studio-র ডান পাশের Workspace Panel।
    @st.fragment থাকায় ফাইল সুইচ বা ডাউনলোডে বাম পাশের ট্রেস রিরান হবে না।
    result shape: {report, files{name: content}, checks{name: bool}, brain, contract_check}
    """
    with st.container(height=640, border=True):
        st.markdown("#### 🧩 Live Workspace & Deliverables")

        if not result:
            st.info(
                "বাম পাশে আপনার প্রোডাকশন ব্রিফ দিয়ে রান শুরু করুন।\n\n"
                "এজেন্টের তৈরি **Final Report**, **কোড**, **ডকুমেন্ট**, **ইমেজ**, **TTS অডিও** "
                "এবং **ffmpeg ভিডিও** এখানে সরাসরি প্রিভিউ ও ডাউনলোড করা যাবে।"
            )
            return

        files: Dict[str, Any] = result.get("files") or {}
        report_text: str = result.get("report") or ""

        # সিলেক্টর অপশন বানানো: Final Report + প্রতিটি ডেলিভারেবল ফাইল
        items: Dict[str, Tuple[str, Any]] = {}
        if report_text:
            items["📄 Final Report"] = ("report.md", report_text)
        for fname, fcontent in files.items():
            items[f"📁 {fname}"] = (fname, fcontent)

        if not items:
            st.caption("এই রানে কোনো রিপোর্ট বা ফাইল তৈরি হয়নি।")
            return

        option_labels = list(items.keys())
        saved_choice = st.session_state.get("studio_selected_item")
        default_idx = option_labels.index(saved_choice) if saved_choice in option_labels else 0

        c_sel, c_dl = st.columns([0.72, 0.28])
        selected_label = c_sel.selectbox(
            "ফাইল নির্বাচন করুন",
            options=option_labels,
            index=default_idx,
            key="studio_ws_selector",
            label_visibility="collapsed",
        )
        st.session_state["studio_selected_item"] = selected_label

        actual_name, actual_content = items[selected_label]
        dl_bytes = _read_download_bytes(actual_content)

        if dl_bytes is not None:
            c_dl.download_button(
                "⬇️ ডাউনলোড",
                data=dl_bytes,
                file_name=os.path.basename(actual_name) or "deliverable.txt",
                key=f"ws_dl_{re.sub(r'[^a-zA-Z0-9_]', '_', actual_name)}",
                use_container_width=True,
            )
        else:
            c_dl.caption("ডিস্কে সেভড")

        st.divider()
        render_file_preview(actual_name, actual_content, key_prefix="studio_ws")


# =========================================================================
# CHAT TAB: অন-ডিমান্ড আর্টিফ্যাক্ট এক্সট্র্যাক্টর ও ওয়ার্কস্পেস (Claude-স্টাইল)
# =========================================================================

def extract_chat_artifact(content: str) -> Optional[Dict[str, str]]:
    """
    চ্যাটের কোনো উত্তরে বড় কোড ব্লক (৮+ লাইন) বা দীর্ঘ রিপোর্ট (৬০০+ অক্ষর) থাকলে
    সেটিকে ক্লিকেবল আর্টিফ্যাক্ট হিসেবে শনাক্ত করে।
    """
    text = str(content or "").strip()
    if not text:
        return None

    # ১. প্রথমে বড় fenced code block খোঁজা
    matches = _FENCED_CODE_RE.findall(text)
    if matches:
        # সবচেয়ে বড় কোড ব্লকটি নেওয়া
        lang, code_body = max(matches, key=lambda m: len(m[1]))
        code_body = code_body.strip()
        if code_body.count("\n") >= 7 or len(code_body) >= 300:
            lang_clean = (lang or "txt").lower().strip()
            ext_map = {
                "python": ".py", "py": ".py", "javascript": ".js", "js": ".js",
                "typescript": ".ts", "ts": ".ts", "html": ".html", "css": ".css",
                "json": ".json", "sql": ".sql", "bash": ".sh", "sh": ".sh",
                "yaml": ".yaml", "yml": ".yaml", "markdown": ".md", "md": ".md",
            }
            ext = ext_map.get(lang_clean, ".txt")
            return {
                "title": f"Code Artifact ({lang_clean or 'text'})",
                "filename": f"artifact{ext}",
                "content": code_body,
            }

    # ২. কোড না থাকলে দীর্ঘ স্ট্রাকচার্ড মার্কডাউন রিপোর্ট (হেডিং বা লিস্টসহ ৬০০+ অক্ষর)
    if len(text) >= 600 and ("##" in text or "\n- " in text or "\n1. " in text or "|" in text):
        first_line = text.splitlines()[0].lstrip("#").strip()[:48]
        return {
            "title": first_line or "Markdown Report",
            "filename": "report.md",
            "content": text,
        }

    return None


@st.fragment
def render_chat_workspace() -> None:
    """Chat ট্যাবের অন-ডিমান্ড ডান প্যানেল। ✖ চাপলে scope='app' রিরান করে ফুল-উইডথ ফিরিয়ে আনে।"""
    artifact = st.session_state.get("chat_active_artifact")
    if not artifact:
        return

    with st.container(height=620, border=True):
        h1, h2 = st.columns([0.85, 0.15])
        h1.markdown(f"#### 🧩 {artifact.get('title', 'Artifact')}")
        if h2.button("✖", key="btn_close_chat_artifact", help="Workspace বন্ধ করুন", use_container_width=True):
            st.session_state["chat_active_artifact"] = None
            st.rerun(scope="app")

        fname = artifact.get("filename", "artifact.md")
        body = artifact.get("content", "")

        st.download_button(
            f"⬇️ {fname} ডাউনলোড",
            data=str(body).encode("utf-8"),
            file_name=fname,
            key="btn_dl_chat_artifact",
            use_container_width=True,
        )
        st.divider()
        render_file_preview(fname, body, key_prefix="chat_ws")
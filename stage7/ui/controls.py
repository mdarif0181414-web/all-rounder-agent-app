# ui/controls.py
import io
import inspect
import os
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
import streamlit as st

# =========================================================================
# ১. BRAIN SWITCHER (সহজ বাংলা লেবেল + আসল ওয়ার্কিং মডেল চেইন — 4 Carbon বাদ)
# =========================================================================

BRAIN_LABELS = {
    "auto": "⚡ স্বয়ংক্রিয়",
    "fast": "🚀 দ্রুত",
    "deep": "🧠 গভীর",
}
LABEL_TO_BRAIN_KEY = {v: k for k, v in BRAIN_LABELS.items()}

BRAIN_HINTS = {
    "auto": "স্বয়ংক্রিয় ব্যালেন্স (ডিফল্ট fallback chain)",
    "fast": "দ্রুততম উত্তর (flash-lite-latest প্রথমে)",
    "deep": "গভীর বিশ্লেষণ ও কোডিং (gemini-3.8-flash প্রথমে)",
}

# আপনার প্রোজেক্টের আসল মডেল আইডি আলাদা থাকলে এখান থেকেই এক জায়গায় বদলাতে পারবেন
FAST_MODEL_ID = "gemini-flash-lite-latest"
DEEP_MODEL_ID = "gemini-3.8-flash"


def resolve_model_chain(
    mode_key: str,
    default_chain: Sequence[str],
    fast_model: str = FAST_MODEL_ID,
    deep_model: str = DEEP_MODEL_ID,
) -> List[str]:
    """
    ইউজারের নির্বাচিত মোড অনুযায়ী ডুপ্লিকেট-মুক্ত মডেল fallback chain ফেরত দেয়।
    4 Carbon API-তে 429 দেয় বলে এখানে রাখা হয়নি।
    """
    base = [m for m in default_chain if m]
    if mode_key == "fast":
        ordered = [fast_model] + [m for m in base if m != fast_model]
    elif mode_key == "deep":
        ordered = [deep_model] + [m for m in base if m != deep_model]
    else:
        ordered = list(base) if base else [fast_model, deep_model]

    # ক্রম ঠিক রেখে ডুপ্লিকেট বাদ দেওয়া
    seen = set()
    result: List[str] = []
    for m in ordered:
        if m not in seen:
            seen.add(m)
            result.append(m)
    return result


def render_brain_switcher() -> str:
    """
    চ্যাটের ওপরে পরিষ্কার ১-লাইনের Brain Switcher রেন্ডার করে।
    রিটার্ন করে: 'auto' | 'fast' | 'deep'
    """
    current_key = st.session_state.get("brain_mode_key", "auto")
    if current_key not in BRAIN_LABELS:
        current_key = "auto"

    c_ctrl, c_hint = st.columns([0.55, 0.45])
    with c_ctrl:
        picked = st.segmented_control(
            "উত্তরের ধরন",
            options=list(BRAIN_LABELS.values()),
            default=BRAIN_LABELS[current_key],
            key="brain_mode_segmented",
            label_visibility="collapsed",
        )
        # segmented_control-এ একই অপশনে দ্বিতীয়বার চাপলে None আসে — তাই পুরনো মান ধরে রাখি
        if picked in LABEL_TO_BRAIN_KEY:
            current_key = LABEL_TO_BRAIN_KEY[picked]
            st.session_state["brain_mode_key"] = current_key

    with c_hint:
        st.caption(f"🎯 {BRAIN_HINTS[current_key]}")

    return current_key


# =========================================================================
# ২. SMART MULTIMODAL INPUT (১ জিবি RAM + টোকেন ক্যাপসহ ফাইল প্রসেসিং)
# =========================================================================

MAX_UPLOAD_FILES = 3
MAX_TEXT_FILE_BYTES = 5 * 1024 * 1024      # 5 MB প্রতি টেক্সট/PDF ফাইল
MAX_IMAGE_FILE_BYTES = 4 * 1024 * 1024     # 4 MB প্রতি ছবি
MAX_TOTAL_CONTEXT_CHARS = 24_000           # ~6k tokens (ফাস্ট চ্যাট ধরে রাখার জন্য)

ALLOWED_UPLOAD_TYPES = [
    "txt", "md", "py", "json", "csv", "sql", "yaml", "yml",
    "html", "css", "js", "ts", "log", "pdf",
    "png", "jpg", "jpeg", "webp",
]

TEXT_EXTS = {
    ".txt", ".md", ".py", ".json", ".csv", ".sql", ".yaml", ".yml",
    ".html", ".css", ".js", ".ts", ".log",
}
IMAGE_MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def render_smart_chat_input(placeholder: str = "যেকোনো প্রশ্ন লিখুন বা ফাইল/ছবি যুক্ত করুন..."):
    """Streamlit 1.43+ মাল্টিমোডাল চ্যাট ইনপুট।"""
    return st.chat_input(
        placeholder,
        accept_file="multiple",
        file_type=ALLOWED_UPLOAD_TYPES,
        key="smart_chat_input",
    )


def parse_chat_submission(raw_value: Any) -> Tuple[str, List[Any]]:
    """
    st.chat_input()-এর রিটার্ন (ChatInputValue অথবা plain str) থেকে
    নিরাপদে (user_text, uploaded_files) আলাদা করে।
    """
    if raw_value is None:
        return "", []
    if isinstance(raw_value, str):
        return raw_value.strip(), []
    text = str(getattr(raw_value, "text", "") or "").strip()
    files = list(getattr(raw_value, "files", None) or [])
    return text, files


def _extract_pdf_text(raw_bytes: bytes, remaining_chars: int) -> Tuple[str, Optional[str]]:
    """ঐচ্ছিক pypdf দিয়ে হালকা PDF টেক্সট এক্সট্র্যাক্টর।"""
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", "PDF পড়ার জন্য requirements.txt-এ `pypdf` যোগ করা প্রয়োজন।"

    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
        chunks: List[str] = []
        collected = 0
        for page_idx, page in enumerate(reader.pages, start=1):
            txt = (page.extract_text() or "").strip()
            if not txt:
                continue
            piece = f"[Page {page_idx}]\n{txt}\n"
            chunks.append(piece)
            collected += len(piece)
            if collected >= remaining_chars:
                break
        combined = "\n".join(chunks).strip()
        if not combined:
            return "", "এই PDF-এ পড়ার মতো টেক্সট পাওয়া যায়নি (সম্ভবত স্ক্যান করা ছবি)।"
        return combined[:remaining_chars], None
    except Exception as exc:
        return "", f"PDF পড়তে সমস্যা হয়েছে: {exc}"


def process_uploaded_files(uploaded_files: Sequence[Any]) -> Dict[str, Any]:
    """
    আপলোড করা ফাইলগুলো যাচাই ও প্রসেস করে ফেরত দেয়:
    {
        "context_text": str,          # LLM প্রম্পটে যোগ করার টেক্সট
        "image_parts": List[dict],    # [{"name", "mime_type", "bytes"}]
        "attachments_meta": List[dict], # history/DB-তে সেভ করার হালকা মেটাডেটা
        "warnings": List[str],        # ইউজারকে দেখানোর সতর্কতা
    }
    """
    files = list(uploaded_files or [])
    warnings: List[str] = []
    if len(files) > MAX_UPLOAD_FILES:
        warnings.append(f"একবারে সর্বোচ্চ {MAX_UPLOAD_FILES}টি ফাইল প্রসেস করা হয়; প্রথম {MAX_UPLOAD_FILES}টি নেওয়া হয়েছে।")
        files = files[:MAX_UPLOAD_FILES]

    context_blocks: List[str] = []
    image_parts: List[Dict[str, Any]] = []
    attachments_meta: List[Dict[str, Any]] = []
    remaining = MAX_TOTAL_CONTEXT_CHARS

    for f in files:
        name = getattr(f, "name", "unnamed")
        ext = os.path.splitext(name)[1].lower()
        raw_bytes = f.getvalue() if hasattr(f, "getvalue") else f.read()
        size_bytes = len(raw_bytes)
        size_kb = round(size_bytes / 1024, 1)

        # ১. ইমেজ ফাইল
        if ext in IMAGE_MIME_MAP:
            if size_bytes > MAX_IMAGE_FILE_BYTES:
                warnings.append(f"`{name}` ৪ MB-এর বেশি ({size_kb} KB) — বাদ দেওয়া হয়েছে।")
                continue
            image_parts.append({
                "name": name,
                "mime_type": IMAGE_MIME_MAP[ext],
                "bytes": raw_bytes,
            })
            attachments_meta.append({"name": name, "kind": "image", "size_kb": size_kb})
            continue

        # ২. টেক্সট / কোড / PDF ফাইল
        if size_bytes > MAX_TEXT_FILE_BYTES:
            warnings.append(f"`{name}` ৫ MB-এর বেশি ({size_kb} KB) — বাদ দেওয়া হয়েছে।")
            continue

        if remaining <= 0:
            warnings.append(f"মোট টেক্সট সীমা ({MAX_TOTAL_CONTEXT_CHARS:,} অক্ষর) পূর্ণ হওয়ায় `{name}` বাদ গেছে।")
            continue

        extracted = ""
        if ext == ".pdf":
            extracted, err = _extract_pdf_text(raw_bytes, remaining)
            if err:
                warnings.append(f"`{name}`: {err}")
                continue
        elif ext in TEXT_EXTS:
            extracted = raw_bytes.decode("utf-8", errors="replace").strip()
            if len(extracted) > remaining:
                extracted = extracted[:remaining]
                warnings.append(f"`{name}` বড় হওয়ায় প্রথম {remaining:,} অক্ষর নেওয়া হয়েছে।")
        else:
            warnings.append(f"`{name}` ফরম্যাটটি ফাস্ট চ্যাটে সমর্থিত নয়।")
            continue

        if extracted:
            context_blocks.append(f"--- [Attached File: {name}] ---\n{extracted}\n--- [End of {name}] ---")
            remaining -= len(extracted)
            attachments_meta.append({"name": name, "kind": ext.lstrip(".") or "text", "size_kb": size_kb})

    return {
        "context_text": "\n\n".join(context_blocks),
        "image_parts": image_parts,
        "attachments_meta": attachments_meta,
        "warnings": warnings,
    }


def build_augmented_prompt(user_text: str, file_bundle: Dict[str, Any]) -> str:
    """ইউজারের প্রশ্ন এবং এক্সট্র্যাক্ট করা ফাইল কনটেক্সট একসাথে LLM প্রম্পটে সাজায়।"""
    ctx = file_bundle.get("context_text", "").strip()
    clean_q = user_text.strip()
    if not clean_q and (ctx or file_bundle.get("image_parts")):
        clean_q = "সংযুক্ত ফাইলটি বিশ্লেষণ করে মূল বিষয়বস্তু বাংলায় বুঝিয়ে দিন।"
    if not ctx:
        return clean_q
    return (
        f"ব্যবহারকারী নিচের ফাইল(গুলো) সংযুক্ত করেছেন। কেবল এই কনটেক্সট ও প্রাসঙ্গিক স্মৃতি ব্যবহার করে উত্তর দিন:\n\n"
        f"{ctx}\n\n"
        f"ব্যবহারকারীর প্রশ্ন:\n{clean_q}"
    )


# =========================================================================
# ৩. FEEDBACK (👍/👎) -> PostgREST PATCH + memory_store.remember()
# =========================================================================

QUICK_LESSON_REASONS = [
    "ভুল বা অসম্পূর্ণ তথ্য",
    "উত্তর অতিরিক্ত লম্বা",
    "মূল প্রশ্ন ঠিকমতো বোঝেনি",
    "বাংলা ভাষা/টোন আরও সহজ হওয়া উচিত",
]


def format_feedback_lesson(user_prompt: str, reason: str, custom_note: str = "") -> str:
    """ভেক্টর মেমোরিতে (RAG) পরিষ্কারভাবে রিকল হওয়ার উপযোগী সংক্ষিপ্ত লেসন ফরম্যাট।"""
    q_short = " ".join(str(user_prompt or "").split())[:140]
    parts = [reason.strip()] if reason.strip() else []
    if custom_note.strip():
        parts.append(custom_note.strip())
    rule = " — ".join(parts) or "উত্তরটি ব্যবহারকারীর প্রত্যাশা অনুযায়ী হয়নি"
    return f"[LESSON | FEEDBACK] এই ধরনের প্রশ্নে ({q_short}) খেয়াল রাখতে হবে: {rule}"


def save_lesson_via_remember(remember_fn: Callable, lesson_text: str) -> bool:
    """
    আপনার memory_store.remember()-এর সিগনেচার (text, source=...) বা (content, source=...)
    স্বয়ংক্রিয়ভাবে মানিয়ে নিয়ে source='FEEDBACK' সহ সেভ করে।
    """
    if remember_fn is None or not lesson_text.strip():
        return False

    sig = inspect.signature(remember_fn)
    params = sig.parameters
    kwargs: Dict[str, Any] = {}

    if "source" in params:
        kwargs["source"] = "FEEDBACK"
    if "kind" in params:
        kwargs["kind"] = "lesson"
    elif "category" in params:
        kwargs["category"] = "lesson"

    remember_fn(lesson_text, **kwargs)
    return True


@st.fragment
def render_feedback_bar(
    msg_index: int,
    msg: Dict[str, Any],
    user_prompt: str,
    chat_store: Any,
    remember_fn: Optional[Callable] = None,
    history_key: str = "history",
) -> None:
    """
    প্রতিটি অ্যাসিস্ট্যান্ট উত্তরের নিচে 👍 / 👎 বাটন রেন্ডার করে।
    @st.fragment থাকায় ফিডব্যাক দিলে পুরো চ্যাট পেজ রিরান হবে না।
    """
    msg_id = msg.get("id")
    current_fb = int(msg.get("feedback") or 0)
    form_key = f"fb_form_open_{msg_index}_{msg_id or 'local'}"

    c_up, c_down, c_status = st.columns([0.10, 0.10, 0.80])

    up_type = "primary" if current_fb == 1 else "secondary"
    down_type = "primary" if current_fb == -1 else "secondary"

    if c_up.button("👍", key=f"fb_up_{msg_index}_{msg_id or 'local'}", type=up_type, help="উত্তর ভালো হয়েছে"):
        st.session_state[history_key][msg_index]["feedback"] = 1
        st.session_state[form_key] = False
        if chat_store and msg_id:
            try:
                chat_store.update_feedback(msg_id, 1)
            except Exception as exc:
                st.toast(f"ফিডব্যাক সিঙ্ক হয়নি: {exc}", icon="⚠️")
        st.toast("ধন্যবাদ! ফিডব্যাক সেভ হয়েছে।", icon="👍")

    if c_down.button("👎", key=f"fb_down_{msg_index}_{msg_id or 'local'}", type=down_type, help="ভুল ছিল — এজেন্টকে শেখান"):
        st.session_state[history_key][msg_index]["feedback"] = -1
        st.session_state[form_key] = True
        if chat_store and msg_id:
            try:
                chat_store.update_feedback(msg_id, -1)
            except Exception as exc:
                st.toast(f"ফিডব্যাক সিঙ্ক হয়নি: {exc}", icon="⚠️")

    if current_fb == 1:
        c_status.caption("✅ ভালো উত্তর হিসেবে চিহ্নিত")
    elif current_fb == -1 and not st.session_state.get(form_key):
        c_status.caption("🧠 সংশোধনী লেসন হিসেবে সংরক্ষিত")

    # 👎 চাপলে ইনলাইন সংশোধনী বক্স (ভেক্টর মেমোরি দূষণ এড়াতে কারণসহ সেভ)
    if st.session_state.get(form_key):
        with st.container(border=True):
            st.caption("🧠 এজেন্ট কী ভুল করেছে? একবার শেখালে পরের বার মনে রাখবে:")
            reason = st.radio(
                "ভুলের ধরন",
                options=QUICK_LESSON_REASONS,
                key=f"fb_reason_{msg_index}_{msg_id or 'local'}",
                horizontal=True,
                label_visibility="collapsed",
            )
            note = st.text_input(
                "বিস্তারিত সংশোধনী (ঐচ্ছিক)",
                placeholder="যেমন: কোড সবসময় সংক্ষেপে এবং বাংলা কমেন্টসহ দেবে...",
                key=f"fb_note_{msg_index}_{msg_id or 'local'}",
            )
            b_save, b_cancel = st.columns([0.5, 0.5])
            if b_save.button("🧠 Lesson Memory-তে সেভ করুন", key=f"fb_save_{msg_index}_{msg_id or 'local'}", type="primary", use_container_width=True):
                lesson_text = format_feedback_lesson(user_prompt, reason, note)
                try:
                    saved = save_lesson_via_remember(remember_fn, lesson_text)
                    st.session_state[form_key] = False
                    if saved:
                        st.toast("নতুন লেসন Supabase memories-এ (source: FEEDBACK) সেভ হয়েছে!", icon="🧠")
                    else:
                        st.toast("ফিডব্যাক মার্ক করা হয়েছে (memory_store কনফিগার করা নেই)।", icon="ℹ️")
                except Exception as exc:
                    st.error(f"লেসন সেভ করতে সমস্যা হয়েছে: {exc}")
            if b_cancel.button("বাদ দিন", key=f"fb_cancel_{msg_index}_{msg_id or 'local'}", use_container_width=True):
                st.session_state[form_key] = False
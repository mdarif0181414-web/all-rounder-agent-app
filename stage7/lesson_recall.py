# lesson_recall.py
from typing import Any, Dict, List, Optional, Sequence
import requests
from ui.auth import _read_cfg


def fetch_feedback_lessons(
    limit: int = 5,
    source_tag: str = "FEEDBACK",
    supabase_url: Optional[str] = None,
    service_key: Optional[str] = None,
    user_id: Optional[str] = None,
    session: Optional[requests.Session] = None,
    timeout: int = 8,
) -> List[str]:
    """
    Supabase `memories` টেবিল থেকে সর্বশেষ FEEDBACK লেসনগুলো আলাদা লেনে (Lane 1) নিয়ে আসে।
    যাতে সাধারণ ভেক্টর সার্চের তথ্যের ভিড়ে আচরণগত নিয়মগুলো হারিয়ে না যায়।
    """
    base = (supabase_url or _read_cfg("SUPABASE_URL")).rstrip("/")
    key = service_key or _read_cfg("SUPABASE_SERVICE_KEY")
    if not base or not key:
        return []

    http = session or requests.Session()
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }
    params: Dict[str, str] = {
        "select": "content",
        "source": f"eq.{source_tag}",
        "order": "created_at.desc",
        "limit": str(limit),
    }
    # ভবিষ্যতে memories টেবিলে user_id কলাম যোগ করলে শুধু user_id পাস করলেই ফিল্টার চালু হবে
    if user_id:
        params["user_id"] = f"eq.{user_id}"

    try:
        resp = http.get(
            f"{base}/rest/v1/memories",
            headers=headers,
            params=params,
            timeout=timeout,
        )
        resp.raise_for_status()
        rows = resp.json() or []
        lessons = []
        seen = set()
        for r in rows:
            txt = str(r.get("content") or "").strip()
            if txt and txt not in seen:
                seen.add(txt)
                lessons.append(txt)
        return lessons
    except Exception:
        return []


def get_cached_lessons(limit: int = 5, force_refresh: bool = False) -> List[str]:
    """
    সেশনে একবারই লোড করে — ফাস্ট চ্যাটে ০ ms বাড়তি সময় লাগবে।
    P5-এ নতুন লেসন সেভ হলে invalidate_lessons_cache() কল করলেই আপডেট হয়ে যাবে।
    """
    import streamlit as st

    if force_refresh or "cached_feedback_lessons" not in st.session_state:
        st.session_state["cached_feedback_lessons"] = fetch_feedback_lessons(limit=limit)
    return list(st.session_state["cached_feedback_lessons"])


def invalidate_lessons_cache() -> None:
    import streamlit as st
    st.session_state.pop("cached_feedback_lessons", None)


def build_system_prompt_with_lessons(
    base_system_prompt: str,
    lessons: Sequence[str],
    max_chars: int = 1800,
) -> str:
    """
    System Instruction-এর শেষে উচ্চ অগ্রাধিকারের Behavioral Lessons ব্লক জুড়ে দেয়।
    """
    cleaned = [str(x).strip() for x in lessons if str(x).strip()]
    if not cleaned:
        return base_system_prompt

    lines: List[str] = []
    total = 0
    for item in cleaned:
        bullet = f"- {item}"
        if total + len(bullet) > max_chars:
            break
        lines.append(bullet)
        total += len(bullet) + 1

    if not lines:
        return base_system_prompt

    block = (
        "\n\n### STRICT BEHAVIORAL LESSONS FROM OWNER FEEDBACK (MUST OBEY)\n"
        "নিচের প্রতিটি নিয়ম ব্যবহারকারীর সরাসরি ফিডব্যাক থেকে শেখা। উত্তর দেওয়ার সময় এগুলো অগ্রাধিকার দিয়ে মেনে চলবে:\n"
        + "\n".join(lines)
    )
    return (base_system_prompt or "").rstrip() + block
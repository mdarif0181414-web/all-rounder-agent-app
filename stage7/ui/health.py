# ui/health.py
import glob
import os
import time
from typing import Any, Dict, List, Sequence
import requests
import streamlit as st
from ui.auth import get_auth_mode, _read_cfg

TEMP_MEDIA_PATTERNS = (
    "/tmp/*.mp4",
    "/tmp/*.mp3",
    "/tmp/*.wav",
    "/tmp/*.png",
    "/tmp/*.jpg",
    "/tmp/agent_out_*",
)


def check_required_secrets(
    gemini_keys: Sequence[str] = ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
) -> Dict[str, Any]:
    """অ্যাপ শুরুতে জরুরি Secrets আছে কি না যাচাই করে (কোনো সিক্রেট ভ্যালু লিক না করে)।"""
    has_gemini = any(bool(_read_cfg(k)) for k in gemini_keys)
    has_sb_url = bool(_read_cfg("SUPABASE_URL"))
    has_sb_key = bool(_read_cfg("SUPABASE_SERVICE_KEY"))

    missing: List[str] = []
    if not has_gemini:
        missing.append("GEMINI_API_KEY / GOOGLE_API_KEY")
    if not has_sb_url:
        missing.append("SUPABASE_URL")
    if not has_sb_key:
        missing.append("SUPABASE_SERVICE_KEY")

    return {
        "ok": len(missing) == 0,
        "gemini": has_gemini,
        "supabase": has_sb_url and has_sb_key,
        "missing": missing,
    }


def ping_supabase_rest(supabase_url: str, service_key: str, timeout: int = 5) -> Dict[str, Any]:
    """হালকা PostgREST পিং (মাত্র ১টি আইডি চেক) — ডেটাবেস জীবিত ও দ্রুত আছে কি না দেখতে।"""
    if not supabase_url or not service_key:
        return {"ok": False, "latency_ms": None, "detail": "Not configured"}
    t0 = time.perf_counter()
    try:
        resp = requests.get(
            f"{supabase_url.rstrip('/')}/rest/v1/chat_sessions",
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
            },
            params={"select": "id", "limit": "1"},
            timeout=timeout,
        )
        ms = round((time.perf_counter() - t0) * 1000)
        if resp.status_code < 400:
            return {"ok": True, "latency_ms": ms, "detail": f"Connected ({ms} ms)"}
        return {"ok": False, "latency_ms": ms, "detail": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"ok": False, "latency_ms": None, "detail": str(exc)[:80]}


@st.cache_data(ttl=60, show_spinner=False)
def _cached_health_snapshot() -> Dict[str, Any]:
    """৬০ সেকেন্ড ক্যাশ — প্রতিটি ক্লিকে Supabase পিং করে চ্যাট স্লো করবে না।"""
    sec = check_required_secrets()
    sb_ping = ping_supabase_rest(_read_cfg("SUPABASE_URL"), _read_cfg("SUPABASE_SERVICE_KEY"))
    return {"secrets": sec, "supabase_ping": sb_ping, "checked_at": time.strftime("%H:%M:%S")}


def cleanup_temp_media(
    max_age_minutes: int = 30,
    patterns: Sequence[str] = TEMP_MEDIA_PATTERNS,
) -> int:
    """
    Streamlit Cloud-এর ফ্রি ১ জিবি RAM ও /tmp ডিস্ক ভরে যাওয়া ঠেকাতে
    পুরনো ffmpeg/TTS/Playwright টেম্প ফাইল মুছে দেয়।
    """
    cutoff = time.time() - (max_age_minutes * 60)
    removed = 0
    for pat in patterns:
        for path in glob.glob(pat):
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
            except OSError:
                pass
    return removed


def render_health_popover(active_models: Sequence[str] = ()) -> None:
    """সাইডবারের নিচে ছোট, নির্ঝঞ্ঝাট System Health পপওভার।"""
    snap = _cached_health_snapshot()
    sec = snap["secrets"]
    sb = snap["supabase_ping"]
    auth_mode = get_auth_mode()

    overall_ok = sec["gemini"] and (sb["ok"] or not sec["supabase"])
    badge = "🟢 সিস্টেম সুস্থ" if overall_ok else "🟡 সতর্কতা দেখুন"

    with st.popover(badge, use_container_width=True):
        st.caption(f"সর্বশেষ যাচাই: {snap['checked_at']}")
        st.markdown(f"- **Gemini API Key:** {'✅ সেট আছে' if sec['gemini'] else '❌ অনুপস্থিত'}")
        st.markdown(f"- **Supabase DB:** {'✅ ' + sb['detail'] if sb['ok'] else '⚠️ ' + sb['detail']}")
        st.markdown(
            f"- **অ্যাক্সেস সুরক্ষা:** "
            f"{'🔐 PIN লকড' if auth_mode == 'pin' else ('🔑 Google OIDC' if auth_mode == 'oidc' else '⚠️ ওপেন (APP_ACCESS_PIN সেট করুন)')}"
        )
        if active_models:
            st.caption("মডেল চেইন: `" + " → ".join(active_models) + "`")

        c1, c2 = st.columns(2)
        if c1.button("🔄 রিফ্রেশ", key="btn_health_refresh", use_container_width=True):
            _cached_health_snapshot.clear()
            st.rerun()
        if c2.button("🧹 /tmp পরিষ্কার", key="btn_tmp_clean", use_container_width=True):
            n = cleanup_temp_media(max_age_minutes=15)
            st.toast(f"{n}টি পুরনো টেম্প ফাইল মোছা হয়েছে।", icon="🧹")
# ui/auth.py
import hmac
import os
import streamlit as st


def _read_cfg(key: str, default: str = "") -> str:
    val = os.getenv(key, "").strip()
    if val:
        return val
    try:
        return str(st.secrets.get(key, default)).strip()
    except Exception:
        return default


def get_auth_mode() -> str:
    """
    'oidc' -> ভবিষ্যৎ Multi-User (Streamlit st.login Google OIDC)
    'pin'  -> বর্তমান Single-User Public App সুরক্ষা (APP_ACCESS_PIN সেট থাকলেই অটো চালু)
    'open' -> লোকাল ডেভেলপমেন্ট / AppTest (কোনো পিন বা OIDC সেট না থাকলে)
    """
    explicit = _read_cfg("APP_AUTH_MODE").lower()
    if explicit in ("oidc", "pin", "open"):
        return explicit
    if _read_cfg("APP_ACCESS_PIN"):
        return "pin"
    return "open"


def get_current_user_id() -> str:
    """পুরো অ্যাপে হার্ডকোডেড 'owner'-এর বদলে এই ফাংশন ব্যবহার করুন।"""
    mode = get_auth_mode()
    if mode == "oidc":
        user_obj = getattr(st, "user", None)
        if user_obj and getattr(user_obj, "is_logged_in", False):
            return str(getattr(user_obj, "email", None) or getattr(user_obj, "name", "user")).lower()
    return str(st.session_state.get("auth_user_id", "owner"))


def verify_pin(entered_pin: str, expected_pin: str) -> bool:
    """Timing-attack নিরাপদ পিন যাচাই।"""
    if not expected_pin:
        return True
    return hmac.compare_digest(str(entered_pin or "").strip(), expected_pin.strip())


def require_access_gate() -> bool:
    """
    app.py-এর শুরুতে (set_page_config ও apply_pro_theme-এর ঠিক পর) কল করুন।
    অথেনটিকেটেড না হলে লগইন স্ক্রিন দেখিয়ে st.stop() করে দেবে।
    """
    mode = get_auth_mode()

    if mode == "open":
        st.session_state["auth_user_id"] = "owner"
        return True

    if mode == "oidc":
        user_obj = getattr(st, "user", None)
        if user_obj and getattr(user_obj, "is_logged_in", False):
            st.session_state["auth_user_id"] = get_current_user_id()
            return True

        st.markdown("### 🔐 সাইন ইন করুন")
        st.caption("আপনার ব্যক্তিগত চ্যাট, মেমোরি ও স্টুডিও ওয়ার্কস্পেস আলাদা রাখতে গুগল দিয়ে লগইন করুন।")
        if st.button("🔑 Google দিয়ে সাইন ইন", type="primary"):
            st.login()
        st.stop()
        return False

    # mode == "pin" (বর্তমান Single-User Public App-এর জন্য সেরা সুরক্ষা)
    expected_pin = _read_cfg("APP_ACCESS_PIN")
    if st.session_state.get("auth_pin_ok") is True:
        return True

    c_l, c_mid, c_r = st.columns([0.25, 0.5, 0.25])
    with c_mid:
        with st.container(border=True):
            st.markdown("### 🔐 প্রাইভেট এজেন্ট অ্যাক্সেস")
            st.caption("এই অ্যাপটি ব্যক্তিগত API ও Supabase মেমোরির সাথে যুক্ত। প্রবেশ করতে পিন দিন।")
            with st.form("pin_login_form", clear_on_submit=True):
                entered = st.text_input("অ্যাক্সেস পিন", type="password", placeholder="আপনার গোপন পিন লিখুন")
                submitted = st.form_submit_button("🔓 প্রবেশ করুন", type="primary", use_container_width=True)

            if submitted:
                if verify_pin(entered, expected_pin):
                    st.session_state["auth_pin_ok"] = True
                    st.session_state["auth_user_id"] = "owner"
                    st.rerun()
                else:
                    st.error("ভুল পিন! অনুগ্রহ করে সঠিক পিন দিন।")
    st.stop()
    return False


def render_logout_button() -> None:
    """সাইডবারের নিচে নিরাপদ লগআউট বাটন (PIN বা OIDC চালু থাকলে)।"""
    mode = get_auth_mode()
    if mode == "pin" and st.session_state.get("auth_pin_ok"):
        if st.button("🔒 লক / লগআউট", key="btn_pin_logout", use_container_width=True):
            st.session_state["auth_pin_ok"] = False
            st.rerun()
    elif mode == "oidc":
        user_obj = getattr(st, "user", None)
        if user_obj and getattr(user_obj, "is_logged_in", False):
            st.caption(f"👤 {get_current_user_id()}")
            if st.button("🚪 লগআউট", key="btn_oidc_logout", use_container_width=True):
                st.logout()
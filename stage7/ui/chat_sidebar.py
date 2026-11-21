# P3: Multi-thread chat sidebar (Neon P3, 2026-11-20)।
# ➕ নতুন চ্যাট (lazy — DB row প্রথম message-এ), session list, খোলা/মোছা।
# Supabase অপ্রাপ্য হলে graceful local mode।
import streamlit as st


def init_chat_state(messages_key="history") -> None:
    if messages_key not in st.session_state:
        st.session_state[messages_key] = []
    if "active_session_id" not in st.session_state:
        st.session_state["active_session_id"] = None
    if "chat_sessions_cache" not in st.session_state:
        st.session_state["chat_sessions_cache"] = None


def refresh_sessions_cache(store, user_id="owner") -> None:
    try:
        st.session_state["chat_sessions_cache"] = store.list_sessions(
            user_id=user_id)
        st.session_state["chat_store_error"] = None
    except Exception as exc:
        st.session_state["chat_sessions_cache"] = []
        st.session_state["chat_store_error"] = str(exc)


def render_chat_sidebar(store, messages_key="history",
                        user_id="owner") -> None:
    init_chat_state(messages_key)
    with st.sidebar:
        st.divider()
        if st.button("➕ নতুন চ্যাট", key="btn_new_chat", type="primary",
                     use_container_width=True):
            st.session_state["active_session_id"] = None
            st.session_state[messages_key] = []
            st.session_state["chat_active_artifact"] = None
            st.rerun()
        if not store.is_configured():
            st.caption("💾 লোকাল সেশন মোড (Supabase key set করা নেই)")
            return
        if st.session_state["chat_sessions_cache"] is None:
            refresh_sessions_cache(store, user_id=user_id)
        if st.session_state.get("chat_store_error"):
            st.warning("চ্যাট হিস্ট্রি লোড করা যায়নি; লোকাল মোডে চলছে।")
            if st.button("🔄 আবার চেষ্টা করুন", key="btn_retry_sessions",
                         use_container_width=True):
                refresh_sessions_cache(store, user_id=user_id)
                st.rerun()
            return
        sessions = st.session_state["chat_sessions_cache"] or []
        active_id = st.session_state.get("active_session_id")
        st.caption(f"সাম্প্রতিক চ্যাট ({len(sessions)})")
        if not sessions:
            st.caption("এখনো কোনো সেভ করা চ্যাট নেই।")
            return
        for s in sessions:
            sid = s["id"]
            title = s.get("title") or "নতুন চ্যাট"
            is_active = sid == active_id
            col_open, col_del = st.columns([0.82, 0.18])
            btn_label = f"🔹 {title}" if is_active else f"💬 {title}"
            if col_open.button(btn_label, key=f"open_sess_{sid}",
                               use_container_width=True):
                try:
                    loaded = store.load_messages(sid)
                    st.session_state["active_session_id"] = sid
                    st.session_state[messages_key] = [
                        {"id": m.get("id"),
                         "role": m["role"], "content": m["content"],
                         "meta": m.get("meta") or {},
                         "tool_trace": m.get("tool_trace") or [],
                         "feedback": int(m.get("feedback") or 0)}
                        for m in loaded]
                    st.session_state["chat_active_artifact"] = None
                    st.rerun()
                except Exception as exc:
                    st.error(f"চ্যাট লোড করতে সমস্যা হয়েছে: {exc}")
            if col_del.button("🗑️", key=f"del_sess_{sid}",
                              help="এই চ্যাট মুছুন"):
                try:
                    store.delete_session(sid)
                    if is_active:
                        st.session_state["active_session_id"] = None
                        st.session_state[messages_key] = []
                        st.session_state["chat_active_artifact"] = None
                    refresh_sessions_cache(store, user_id=user_id)
                    st.rerun()
                except Exception as exc:
                    st.error(f"মুছতে ব্যর্থ: {exc}")

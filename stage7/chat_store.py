# P3: Multi-thread chat history store (Neon P3, 2026-11-20)।
# memory_store.py-এর মতোই Supabase PostgREST (requests + service key) —
# supabase-py যোগ করা হয়নি (RAM/dependency বাঁচাতে, Neon-এর সিদ্ধান্ত)।
# Table দুটো (chat_sessions, chat_messages) owner SQL Editor-এ বানাবেন;
# table না থাকলে store graceful — app local mode-এ চলতে থাকে।
import os
import re

import requests


def _read_secret_or_env(key: str) -> str:
    val = os.getenv(key, "").strip()
    if val:
        return val
    try:
        import streamlit as st
        return str(st.secrets.get(key, "")).strip()
    except Exception:
        return ""


def make_session_title(first_prompt: str, max_len: int = 48) -> str:
    cleaned = re.sub(r"\s+", " ", str(first_prompt or "")).strip()
    if not cleaned:
        return "নতুন চ্যাট"
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len - 1].rstrip() + "…"


class ChatStore:
    def __init__(self, supabase_url=None, service_key=None, timeout=10,
                 session=None):
        self.base_url = (supabase_url
                         or _read_secret_or_env("SUPABASE_URL")).rstrip("/")
        self.service_key = (service_key
                            or _read_secret_or_env("SUPABASE_SERVICE_KEY"))
        self.timeout = timeout
        self.http = session or requests.Session()

    def is_configured(self) -> bool:
        return bool(self.base_url and self.service_key)

    def _headers(self, prefer=None):
        h = {"apikey": self.service_key,
             "Authorization": f"Bearer {self.service_key}",
             "Content-Type": "application/json"}
        if prefer:
            h["Prefer"] = prefer
        return h

    def _url(self, table: str) -> str:
        return f"{self.base_url}/rest/v1/{table}"

    def list_sessions(self, user_id="owner", limit=30):
        if not self.is_configured():
            return []
        resp = self.http.get(
            self._url("chat_sessions"), headers=self._headers(),
            params={"select": "id,title,created_at,updated_at",
                    "user_id": f"eq.{user_id}",
                    "order": "updated_at.desc", "limit": str(limit)},
            timeout=self.timeout)
        resp.raise_for_status()
        return resp.json() or []

    def create_session(self, title="নতুন চ্যাট", user_id="owner"):
        if not self.is_configured():
            return None
        resp = self.http.post(
            self._url("chat_sessions"),
            headers=self._headers(prefer="return=representation"),
            json={"user_id": user_id, "title": make_session_title(title)},
            timeout=self.timeout)
        resp.raise_for_status()
        rows = resp.json() or []
        return rows[0] if rows else None

    def rename_session(self, session_id, new_title):
        if not self.is_configured() or not session_id:
            return False
        resp = self.http.patch(
            self._url("chat_sessions"), headers=self._headers(),
            params={"id": f"eq.{session_id}"},
            json={"title": make_session_title(new_title)},
            timeout=self.timeout)
        resp.raise_for_status()
        return True

    def delete_session(self, session_id):
        if not self.is_configured() or not session_id:
            return False
        resp = self.http.delete(
            self._url("chat_sessions"), headers=self._headers(),
            params={"id": f"eq.{session_id}"}, timeout=self.timeout)
        resp.raise_for_status()
        return True

    def load_messages(self, session_id, limit=200):
        if not self.is_configured() or not session_id:
            return []
        resp = self.http.get(
            self._url("chat_messages"), headers=self._headers(),
            params={"select": "id,role,content,meta,tool_trace,feedback,"
                              "created_at",
                    "session_id": f"eq.{session_id}",
                    "order": "created_at.asc", "limit": str(limit)},
            timeout=self.timeout)
        resp.raise_for_status()
        return resp.json() or []

    def append_message(self, session_id, role, content, meta=None,
                       tool_trace=None):
        if not self.is_configured() or not session_id:
            return None
        payload = {"session_id": session_id, "role": role,
                   "content": content, "meta": meta or {},
                   "tool_trace": tool_trace or []}
        resp = self.http.post(
            self._url("chat_messages"),
            headers=self._headers(prefer="return=representation"),
            json=payload, timeout=self.timeout)
        resp.raise_for_status()
        rows = resp.json() or []
        return rows[0] if rows else None


def get_cached_chat_store() -> ChatStore:
    import streamlit as st

    @st.cache_resource
    def _build() -> ChatStore:
        return ChatStore()

    return _build()

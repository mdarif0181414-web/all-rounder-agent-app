# stage7/job_store.py
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests


def _read_cfg(key: str) -> str:
    val = os.getenv(key, "").strip()
    if val:
        return val
    try:
        import streamlit as st
        return str(st.secrets.get(key, "")).strip()
    except Exception:
        return ""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    """
    chat_store.py ও memory_store.py-এর মতোই Supabase PostgREST ব্যবহার করে
    agent_jobs কিউ পরিচালনা করে।
    """

    def __init__(
        self,
        supabase_url: Optional[str] = None,
        service_key: Optional[str] = None,
        timeout: int = 12,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = (supabase_url or _read_cfg("SUPABASE_URL")).rstrip("/")
        self.service_key = service_key or _read_cfg("SUPABASE_SERVICE_KEY")
        self.timeout = timeout
        self.http = session or requests.Session()

    def is_configured(self) -> bool:
        return bool(self.base_url and self.service_key)

    def _headers(self, prefer: Optional[str] = None) -> Dict[str, str]:
        h = {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Content-Type": "application/json",
        }
        if prefer:
            h["Prefer"] = prefer
        return h

    def _url(self) -> str:
        return f"{self.base_url}/rest/v1/agent_jobs"

    def enqueue_job(
        self,
        brief: str,
        project_tag: str = "general",
        user_id: str = "owner",
        priority: int = 0,
    ) -> Optional[Dict[str, Any]]:
        if not self.is_configured() or not brief.strip():
            return None
        resp = self.http.post(
            self._url(),
            headers=self._headers(prefer="return=representation"),
            json={
                "user_id": user_id,
                "project_tag": (project_tag or "general").strip()[:60],
                "brief": brief.strip(),
                "priority": int(priority),
                "status": "pending",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        rows = resp.json() or []
        return rows[0] if rows else None

    def list_jobs(self, user_id: str = "owner", limit: int = 20) -> List[Dict[str, Any]]:
        if not self.is_configured():
            return []
        resp = self.http.get(
            self._url(),
            headers=self._headers(),
            params={
                "select": "id,project_tag,brief,status,priority,brain,contract_check,result_files_meta,github_run_url,error_message,created_at,completed_at",
                "user_id": f"eq.{user_id}",
                "order": "created_at.desc",
                "limit": str(limit),
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json() or []

    def claim_next_pending_job(self, github_run_url: str = "") -> Optional[Dict[str, Any]]:
        """
        Optimistic locking: প্রথমে ১টি pending জব দেখে, তারপর কেবল status='pending' থাকলেই
        'running'-এ আপডেট করে। এতে দুইটি রানার একই জব ডাবল-রান করতে পারে না।
        """
        if not self.is_configured():
            return None
        resp = self.http.get(
            self._url(),
            headers=self._headers(),
            params={
                "select": "id,user_id,project_tag,brief,priority",
                "status": "eq.pending",
                "order": "priority.desc,created_at.asc",
                "limit": "1",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        candidates = resp.json() or []
        if not candidates:
            return None

        job_id = candidates[0]["id"]
        patch_resp = self.http.patch(
            self._url(),
            headers=self._headers(prefer="return=representation"),
            params={"id": f"eq.{job_id}", "status": "eq.pending"},
            json={
                "status": "running",
                "started_at": _utc_now_iso(),
                "github_run_url": github_run_url or None,
            },
            timeout=self.timeout,
        )
        patch_resp.raise_for_status()
        claimed = patch_resp.json() or []
        return claimed[0] if claimed else None

    def complete_job(
        self,
        job_id: str,
        report: str,
        checks: Dict[str, Any],
        contract_check: Dict[str, Any],
        files_meta: List[Dict[str, Any]],
        tool_trace: List[Dict[str, Any]],
        brain: str = "",
        github_run_url: str = "",
    ) -> bool:
        if not self.is_configured() or not job_id:
            return False
        resp = self.http.patch(
            self._url(),
            headers=self._headers(),
            params={"id": f"eq.{job_id}"},
            json={
                "status": "completed",
                "brain": brain or None,
                "result_report": (report or "")[:60_000],
                "result_checks": checks or {},
                "contract_check": contract_check or {},
                "result_files_meta": files_meta or [],
                "tool_trace": tool_trace[-120:],  # DB হালকা রাখতে শেষ ১২০ ইভেন্ট
                "github_run_url": github_run_url or None,
                "error_message": None,
                "completed_at": _utc_now_iso(),
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return True

    def fail_job(self, job_id: str, error_message: str, tool_trace: Optional[List[Dict[str, Any]]] = None) -> bool:
        if not self.is_configured() or not job_id:
            return False
        resp = self.http.patch(
            self._url(),
            headers=self._headers(),
            params={"id": f"eq.{job_id}"},
            json={
                "status": "failed",
                "error_message": str(error_message or "Unknown error")[:2000],
                "tool_trace": (tool_trace or [])[-120:],
                "completed_at": _utc_now_iso(),
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return True
# Standard event schema (Neon P1, 2026-11-20) — Production Studio-র
# live trace এবং ভবিষ্যৎ P3 (Supabase JSONB)-এর common contract।
# প্রতিটা event JSON-serializable dict।
import time
from typing import Dict, Optional

EVENT_TYPES = (
    "run_start", "thought", "tool_start", "tool_end", "tool_error",
    "gate_check", "deliverable", "token", "run_complete", "run_error",
)


def make_event(event_type: str, step: int = 0, max_steps: int = 30,
               **payload) -> Dict:
    return {"type": event_type, "step": step, "max_steps": max_steps,
            "ts": round(time.time(), 3), **payload}


def event_to_legacy_log(event: Dict) -> Optional[str]:
    """পুরনো log(str) callback-এর জন্য এক লাইনের রূপ (backward compat)।"""
    t = event.get("type")
    step = event.get("step", 0)
    mx = event.get("max_steps", 30)
    if t == "thought":
        return f"[Step {step}/{mx}] Thinking: {event.get('content', '')}"
    if t == "tool_start":
        return f"[Step {step}/{mx}] Running tool: {event.get('tool', '')}"
    if t == "tool_end":
        return (f"[Step {step}/{mx}] Done: {event.get('tool', '')} "
                f"({event.get('duration_sec', '?')}s)")
    if t == "tool_error":
        return (f"[Step {step}/{mx}] Tool error in "
                f"{event.get('tool', '')}: {event.get('error', '')}")
    if t == "gate_check":
        mark = "PASS" if event.get("passed") else "FAIL"
        return f"[Gate Check] {event.get('check_name', '')}: {mark}"
    if t == "run_error":
        return f"[Error] {event.get('error', '')}"
    return None

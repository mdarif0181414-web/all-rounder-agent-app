# stage7/worker.py
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import requests

from job_store import JobStore


def _is_disk_file(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\n" in value or "\x00" in value or len(value) > 512:
        return False
    try:
        return os.path.isfile(value)
    except OSError:
        return False


def save_deliverables_to_dir(
    output_dir: Path,
    report: str,
    files: Dict[str, Any],
    checks: Dict[str, Any],
    trace_log: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    run_produce থেকে পাওয়া {report, files{name: content}, checks} ডিস্কে সেভ করে
    (GitHub Actions Artifact হিসেবে ডাউনলোড করার জন্য) এবং হালকা মেটাডেটা লিস্ট ফেরত দেয়।
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_meta: List[Dict[str, Any]] = []

    if report:
        report_path = output_dir / "REPORT.md"
        report_path.write_text(str(report), encoding="utf-8")
        saved_meta.append({"name": "REPORT.md", "size_kb": round(report_path.stat().st_size / 1024, 1)})

    meta_path = output_dir / "run_metadata.json"
    meta_path.write_text(
        json.dumps({"checks": checks or {}, "trace_events": len(trace_log)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for raw_name, content in (files or {}).items():
        safe_name = os.path.basename(str(raw_name).strip()) or "unnamed.txt"
        dest = output_dir / safe_name

        if _is_disk_file(content):
            if Path(content).resolve() != dest.resolve():
                shutil.copy2(content, dest)
        elif isinstance(content, bytes):
            dest.write_bytes(content)
        else:
            dest.write_text(str(content or ""), encoding="utf-8")

        saved_meta.append({"name": safe_name, "size_kb": round(dest.stat().st_size / 1024, 1)})

    return saved_meta


def send_telegram_alert(message: str) -> bool:
    """
    ঐচ্ছিক ফ্রি নোটিফিকেশন: TELEGRAM_BOT_TOKEN ও TELEGRAM_CHAT_ID সেট থাকলে
    জব শেষ হওয়ার সাথে সাথে আপনার ফোনে রিপোর্ট পাঠাবে।
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message[:3900]},
            timeout=8,
        )
        return resp.status_code < 400
    except Exception:
        return False


def build_github_run_url() -> str:
    server = os.getenv("GITHUB_SERVER_URL", "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    run_id = os.getenv("GITHUB_RUN_ID", "").strip()
    if server and repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return ""


def execute_single_job(
    store: JobStore,
    run_produce_fn: Callable,
    artifacts_root: Path = Path("artifacts"),
    manual_brief: str = "",
    project_tag: str = "manual_dispatch",
) -> str:
    """
    একটি জব প্রসেস করে। রিটার্ন করে: 'completed' | 'failed' | 'empty'
    """
    run_url = build_github_run_url()

    # ১. ম্যানুয়াল ব্রিফ দিলে কিউতে এন্ট্রি করে সাথে সাথে ক্লেইম করা; নইলে কিউ থেকে নেওয়া
    if manual_brief.strip():
        if store.is_configured():
            enqueued = store.enqueue_job(brief=manual_brief.strip(), project_tag=project_tag, priority=10)
            job = store.claim_next_pending_job(github_run_url=run_url) if enqueued else None
        else:
            job = {"id": f"local_{int(time.time())}", "project_tag": project_tag, "brief": manual_brief.strip()}
    else:
        job = store.claim_next_pending_job(github_run_url=run_url)

    if not job:
        print("ℹ️ কোনো pending জব নেই — ওয়ার্কার পরিষ্কারভাবে বন্ধ হচ্ছে।")
        return "empty"

    job_id = str(job["id"])
    brief = str(job["brief"])
    tag = str(job.get("project_tag", "general"))
    print(f"🚀 জব শুরু হয়েছে | ID: {job_id} | Project: {tag}")

    trace_log: List[Dict[str, Any]] = []

    def on_event(ev: Dict[str, Any]) -> None:
        if ev.get("type") != "token":
            trace_log.append(ev)
        etype = ev.get("type")
        if etype in ("tool_start", "tool_end", "tool_error", "gate_check"):
            print(f"  [{ev.get('step', 0)}] {etype}: {ev.get('tool') or ev.get('check_name') or ''}")

    t0 = time.perf_counter()
    try:
        result = run_produce_fn(brief, on_event=on_event) or {}
        elapsed = round(time.perf_counter() - t0, 1)

        report = str(result.get("report") or "")
        files = result.get("files") or {}
        checks = result.get("checks") or {}
        brain = str(result.get("brain") or "")
        contract_check = result.get("contract_check") or {
            "passed": all(bool(v) for v in checks.values()) if checks else True,
            "details": "Completed in 24/7 headless worker",
        }

        out_dir = artifacts_root / f"{tag}_{job_id[:8]}"
        files_meta = save_deliverables_to_dir(out_dir, report, files, checks, trace_log)

        if store.is_configured():
            store.complete_job(
                job_id=job_id,
                report=report,
                checks=checks,
                contract_check=contract_check,
                files_meta=files_meta,
                tool_trace=trace_log,
                brain=brain,
                github_run_url=run_url,
            )

        status_icon = "✅" if contract_check.get("passed", True) else "⚠️"
        msg = (
            f"{status_icon} 24/7 Agent Job সম্পন্ন ({elapsed}s)\n"
            f"Project: {tag}\n"
            f"Files: {len(files_meta)}টি\n"
            f"Run: {run_url or str(out_dir)}"
        )
        print(msg)
        send_telegram_alert(msg)
        return "completed"

    except Exception as exc:
        err_str = f"{type(exc).__name__}: {exc}"
        print(f"❌ জব ব্যর্থ হয়েছে ({job_id}): {err_str}", file=sys.stderr)
        if store.is_configured():
            store.fail_job(job_id=job_id, error_message=err_str, tool_trace=trace_log)
        send_telegram_alert(f"❌ 24/7 Agent Job ব্যর্থ ({tag}): {err_str[:300]}\n{run_url}")
        return "failed"


def main() -> int:
    parser = argparse.ArgumentParser(description="24/7 Autonomous Agent Worker")
    parser.add_argument("--brief", default="", help="ঐচ্ছিক ম্যানুয়াল ব্রিফ (workflow_dispatch-এর জন্য)")
    parser.add_argument("--project", default="general", help="চ্যানেল বা ক্লায়েন্ট ট্যাগ")
    parser.add_argument("--max-jobs", type=int, default=1, help="এক রানে সর্বোচ্চ কয়টি জব প্রসেস করবে")
    args = parser.parse_args()

    # আপনার আসল run_produce ফাংশনটি যে মডিউলে আছে, সেই ফ্ল্যাট ইমপোর্ট পাথ দিন
    # উদাহরণ: from studio_core import run_produce  অথবা  from core import run_produce
    from agent_app_core import run_produce  # <-- আপনার আসল ফাইলের নাম মিলিয়ে নেবেন

    store = JobStore()
    had_failure = False

    if args.brief.strip():
        outcome = execute_single_job(
            store=store,
            run_produce_fn=run_produce,
            manual_brief=args.brief,
            project_tag=args.project,
        )
        return 1 if outcome == "failed" else 0

    for _ in range(max(1, args.max_jobs)):
        outcome = execute_single_job(store=store, run_produce_fn=run_produce)
        if outcome == "empty":
            break
        if outcome == "failed":
            had_failure = True

    return 1 if had_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
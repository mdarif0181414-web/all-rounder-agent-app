# Agent v8 (development phase, step 2 — 2026-11-18): v7 + measure_file tool.
# The agent can now MEASURE its own files exactly (words / CSV rows /
# duration totals) instead of guessing numbers. Everything else = v7.
import csv
import json
import os
import re
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE7 = os.path.join(HERE, "..", "stage7")
sys.path.insert(0, os.path.abspath(STAGE7))
sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")

WORK = os.path.join(HERE, "work_complex2")
os.makedirs(WORK, exist_ok=True)

if "--unit-test" not in sys.argv and "GEMINI_API_KEY" not in os.environ:
    # Workshop: load the agent key from the Secure Vault connector.
    # Hosted app: GEMINI_API_KEY already set from app secrets — skip.
    try:
        from dynamic_credentials import dynamic_credential_entry
        entry = dynamic_credential_entry("custom.google-ai-studio-agent")
        os.environ["GEMINI_API_KEY"] = str(entry["surrogate"]).strip()
    except Exception:
        pass
    os.environ.setdefault("STAGE2_APPROVAL", "deny")


def relay_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 18080), timeout=2):
            return True
    except OSError:
        return False


_RELAY = os.path.join(STAGE7, "..", "stage3", "relay_proxy.py")
if "--unit-test" not in sys.argv and not relay_up() \
        and os.path.exists(_RELAY):
    subprocess.Popen([sys.executable, _RELAY],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
os.environ.setdefault("AGENT_BROWSER_PROXY", "http://127.0.0.1:18080")

import agent_v7 as v7  # noqa: E402
from pydantic import BaseModel  # noqa: E402

v7.WORK_DIR = WORK
v7.base.WORK_DIR = WORK


class MeasureArgs(BaseModel):
    filename: str


def measure_file(filename: str) -> str:
    """Measure a file in your work folder EXACTLY — never guess numbers.

    For a text/markdown file: returns total word count and narration word
    count (markdown headers and [bracketed] markers excluded), plus line
    and character counts. For a CSV file: returns the header, the number
    of data rows, how many rows are malformed (wrong field count), and —
    when the last column is numeric — the exact sum of that column
    (e.g. total duration_seconds).

    Use this BEFORE finishing any task with a numeric contract (word
    counts, row counts, durations): write the file, measure it, and if
    the numbers miss the contract, fix the file and measure again.

    Args:
        filename: Name of the file inside the work folder.
    Returns:
        JSON string with the exact measurements.
    """
    path = os.path.normpath(os.path.join(WORK, filename))
    if not path.startswith(os.path.normpath(WORK) + os.sep):
        return json.dumps({"status": "error",
                           "error": "work folder-এর বাইরে যাওয়া যায় না"})
    if not os.path.exists(path):
        return json.dumps({"status": "error", "error": "file নেই"},
                          ensure_ascii=False)
    try:
        if filename.lower().endswith(".csv"):
            rows = list(csv.reader(open(path, encoding="utf-8")))
            header, data = rows[0], rows[1:]
            bad, total, numeric = 0, 0.0, True
            for r in data:
                if len(r) != len(header):
                    bad += 1
                    continue
                try:
                    total += float(r[-1])
                except ValueError:
                    numeric = False
            out = {"status": "ok", "file": filename, "header": header,
                   "data_rows": len(data), "malformed_rows": bad}
            if numeric and data:
                out["last_column_total"] = total
            return json.dumps(out, ensure_ascii=False)
        txt = open(path, encoding="utf-8").read()
        lines = [ln for ln in txt.splitlines()
                 if not ln.strip().startswith("#")]
        clean = re.sub(r"\[[^\]]*\]", " ", "\n".join(lines))
        return json.dumps(
            {"status": "ok", "file": filename,
             "words_total": len(txt.split()),
             "words_narration": len(clean.split()),
             "lines": len(txt.splitlines()), "chars": len(txt)},
            ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error",
                           "error": f"{type(e).__name__}: {e}"},
                          ensure_ascii=False)


# Register the new tool into v7's tables (run_agent reads them live).
v7.TOOLS = v7.TOOLS + [measure_file]
v7.SCHEMAS = {**v7.SCHEMAS, measure_file: MeasureArgs}
v7.TOOL_MAP = {fn.__name__: fn for fn in v7.TOOLS}
v7.SYSTEM += (
    "\n\nNEW TOOL — measure_file: কোনো file-এর শব্দসংখ্যা, CSV row সংখ্যা "
    "বা মোট duration জানতে কখনো অনুমান করবে না; measure_file দিয়ে মেপে "
    "তারপরই সংখ্যা বলবে বা সিদ্ধান্ত নেবে। Numeric contract থাকলে জমা "
    "দেওয়ার আগে অবশ্যই measure করে যাচাই করবে।")

MISSION = """SELF-CHECK MISSION — তোমার work folder-এ একটা video package আছে। বাইরের checker মেপে পেয়েছে:
- script.md-এর narration = 560 শব্দ — contract 650–750। এটাই একমাত্র সমস্যা।
- shot_list.csv = 14 shot, মোট 280s — PASS করেছে। ওটা বদলাবে না, ছোঁবেও না।
- research_notes.md ও seo_package.md — PASS, ছোঁবে না।

তোমার একমাত্র কাজ: script.md নতুন করে লিখে narration 650–750 শব্দে আনা।
- পুরনো script prev_script.md নামে রাখা আছে — ওটা আর research_notes.md পড়ে, একই topic ("The 86 Billion Neuron Universe"), একই hook ও closing line রেখে সম্প্রসারণ করবে। নতুন কোনো invented statistics নয় — শুধু research notes ও পুরনো script-এর তথ্য।
- তোমার কাছে নতুন tool আছে: measure_file — এটা হুবহু গুনে দেয়। প্রথমে prev_script.md measure করে দেখে নাও; নতুন script.md লেখার পর measure করবে; 650–750-এর বাইরে হলে আবার ঠিক করে আবার measure করবে — সীমার ভেতরে না আসা পর্যন্ত চেষ্টা চালিয়ে যাবে।
- শেষে demo_report.md নতুন করে বাংলায় লিখবে: কী সমস্যা ছিল, কী করলে, আর measure_file থেকে পাওয়া চূড়ান্ত সংখ্যাগুলো হুবহু বসাবে (শুধু tool-এর দেওয়া সংখ্যাই লিখবে, নিজে বানাবে না)।"""

if __name__ == "__main__":
    if "--unit-test" in sys.argv:
        for f in ("prev_script.md", "shot_list.csv"):
            print(f, "->", measure_file(f))
        sys.exit(0)
    print(f"[v8] work dir: {WORK} | memory: {v7.base6.STORE.name}",
          flush=True)
    for model in v7.MODELS:
        print(f"\n=== Brain: {model} ===", flush=True)
        try:
            out = v7.run_agent(MISSION, model)
        except Exception as e:
            print(f"⚠️ {model} ব্যর্থ ({type(e).__name__}: {e}) — fallback...",
                  flush=True)
            continue
        print("\n================ V8 REPORT ================", flush=True)
        print(out, flush=True)
        break
    print("[v8] DONE", flush=True)

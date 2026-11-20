# Agent v9 (development phase, step 3 — 2026-11-18): v8 + append_text_file.
# Appending grows a file by a measured amount instead of gambling on a
# full rewrite — the fix for the corrective round's 2-4-words-per-round
# crawl. Append is additive (never destroys existing content), so it
# does not need the overwrite gate.
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import agent_v8 as v8  # noqa: E402  (key, relay, v7 + measure_file setup)

WORK = os.path.join(HERE, "work_complex4")
os.makedirs(WORK, exist_ok=True)
v8.WORK = WORK
v8.v7.WORK_DIR = WORK
v8.v7.base.WORK_DIR = WORK

from pydantic import BaseModel  # noqa: E402


class AppendArgs(BaseModel):
    filename: str
    content: str


def append_text_file(filename: str, content: str) -> str:
    """Append text to the END of an existing file in your work folder.

    The file must already exist (use write_text_file to create it). The
    existing content is never changed or deleted — your text is added
    after it. Use this to GROW a file by a controlled amount: first
    measure_file to learn the current size and the exact deficit, then
    append one block sized to cover the deficit, then measure again.

    Args:
        filename: Name of the existing file inside the work folder.
        content: The text block to add at the end.
    Returns:
        JSON string with status and the new file size in bytes.
    """
    path = os.path.normpath(os.path.join(WORK, filename))
    if not path.startswith(os.path.normpath(WORK) + os.sep):
        return json.dumps({"status": "error",
                           "error": "work folder-এর বাইরে যাওয়া যায় না"})
    if not os.path.exists(path):
        return json.dumps({"status": "error",
                           "error": "file নেই — আগে write_text_file দিয়ে "
                                    "তৈরি করো"}, ensure_ascii=False)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n" + content.strip() + "\n")
        return json.dumps({"status": "ok", "filename": filename,
                           "added_chars": len(content),
                           "new_bytes": os.path.getsize(path)},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error",
                           "error": f"{type(e).__name__}: {e}"},
                          ensure_ascii=False)


v7 = v8.v7
v7.TOOLS = v7.TOOLS + [append_text_file]
v7.SCHEMAS = {**v7.SCHEMAS, append_text_file: AppendArgs}
v7.TOOL_MAP = {fn.__name__: fn for fn in v7.TOOLS}
v7.SYSTEM += (
    "\n\nNEW TOOL — append_text_file: কোনো file বড় করতে হলে পুরোটা আবার "
    "লিখবে না। আগে measure_file দিয়ে ঘাটতি জানবে, তারপর append_text_file "
    "দিয়ে ঘাটতি মাপের একটা block জুড়ে দেবে, তারপর আবার measure করে "
    "নিশ্চিত হবে।")

CLOSING = ("So the very next time you wonder who you really are, remember "
           "this fundamental truth: you are not just holding the universe; "
           "you are the universe, wondering about itself.")

MISSION = f"""APPEND MISSION — তোমার work folder-এর script.md-তে একটা narration script-এর প্রথম ৭টা scene আছে। Closing scene-টা ইচ্ছা করে সরিয়ে রাখা হয়েছে — ওটা শেষে তুমি জুড়বে। Contract: script.md-এর মোট narration 650–750 শব্দ।

ধাপগুলো:
1. measure_file দিয়ে script.md মাপো — এখন কত শব্দ, 650-তে পৌঁছাতে ঘাটতি কত, হিসাব করো।
2. research_notes.md থেকে আসল তথ্য নিয়ে একটা নতুন scene লেখো — আকার এমন হবে যাতে নতুন scene + closing মিলিয়ে মোট শব্দ ~690 হয় (ঘাটতি + প্রায় 45 শব্দ)। নতুন invented statistics নয়।
3. append_text_file দিয়ে script.md-তে একবারের append-এ দুটো block জুড়বে: প্রথমে নতুন scene-টা [Scene 8] হিসেবে, তারপর [Scene 9] হিসেবে এই closing লাইনটা হুবহু:
"{CLOSING}"
4. আবার measure_file দিয়ে script.md মাপো। 650–750-এর ভেতরে থাকলে থেমে যাও। কম হলে: আরও একটা ছোট scene append করো, তারপর closing লাইনটা আবার সবার শেষে append করে দাও (report-এ সৎভাবে লিখবে যে closing দুবার এসেছে)। বেশি (750+) হলে report-এ সৎভাবে জানাবে — নিজে কিছু মুছতে যাবে না।
5. demo_report.md বাংলায় লেখো: measure থেকে পাওয়া শুরুর সংখ্যা, কত শব্দের block জুড়লে, চূড়ান্ত সংখ্যা, আর তুলনাটা হুবহু এইভাবে — "চূড়ান্ত narration = X শব্দ; X ≥ 650: সত্য/মিথ্যা; X ≤ 750: সত্য/মিথ্যা"। শুধু tool-এর দেওয়া সংখ্যাই লিখবে।
6. shot_list.csv, research_notes.md, seo_package.md ছোঁবে না — ওগুলো PASS আছে।"""

if __name__ == "__main__":
    if "--unit-test" in sys.argv:
        p = os.path.join(WORK, "scratch.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("[Scene 1]\none two three four five six seven eight nine ten\n")
        print("before:", v8.measure_file("scratch.txt"))
        print(append_text_file(
            "scratch.txt",
            "[Scene 2]\nalpha bravo charlie delta echo foxtrot golf hotel india juliet"))
        print("after:", v8.measure_file("scratch.txt"))
        os.remove(p)
        sys.exit(0)
    print(f"[v9] work dir: {WORK} | memory: {v7.base6.STORE.name}",
          flush=True)
    for model in v7.MODELS:
        print(f"\n=== Brain: {model} ===", flush=True)
        try:
            out = v7.run_agent(MISSION, model)
        except Exception as e:
            print(f"⚠️ {model} ব্যর্থ ({type(e).__name__}: {e}) — fallback...",
                  flush=True)
            continue
        print("\n================ V9 REPORT ================", flush=True)
        print(out, flush=True)
        break
    print("[v9] DONE", flush=True)

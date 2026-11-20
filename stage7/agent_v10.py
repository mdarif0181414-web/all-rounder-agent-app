# Agent v10 (development phase, step 4 — 2026-11-19): v9 + scan_text tool.
# scan_text gives the agent mechanical evidence for a content-quality
# pass: meta/process phrases (things a viewer should never hear),
# repeated sentences, and every statistic claim in the text (to check
# against sources). Judgment stays with the agent; facts come from tools.
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import agent_v9 as v9  # noqa: E402  (key, relay, v7 + measure + append)

WORK = os.path.join(HERE, "work_complex5")
os.makedirs(WORK, exist_ok=True)
v9.v8.WORK = WORK
v9.WORK = WORK
v9.v7.WORK_DIR = WORK
v9.v7.base.WORK_DIR = WORK

from pydantic import BaseModel  # noqa: E402


class ScanArgs(BaseModel):
    filename: str


META_PATTERNS = [
    "research note", "our research", "the research notes",
    "viewers drawn", "million viewers", "subscribers", "this channel",
    "word count", "in this script", "the script says", "as an ai",
    "demo report", "shot list",
]
STAT_RE = re.compile(
    r"\b\d[\d,\.]*\s*(?:billion|million|trillion|thousand|percent|%|"
    r"miles per hour|mph|watts?|pounds?|petabytes?|hours?|years?|times)\b",
    re.IGNORECASE)
# The scripts spell numbers out ("eighty-six billion") — catch those too:
# a unit word preceded by up to 6 number-word tokens.
NUMWORDS = {
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty",
    "fifty", "sixty", "seventy", "eighty", "ninety", "hundred", "thousand",
    "million", "billion", "trillion", "point", "and",
}
UNITS = {"billion", "million", "trillion", "thousand", "percent", "watts",
         "watt", "pounds", "pound", "petabytes", "petabyte", "hours",
         "hour", "years", "year", "times", "mph"}


def spelled_stats(txt: str):
    found = set()
    tokens = re.findall(r"[A-Za-z][A-Za-z\-]*|\d[\d,\.]*", txt)
    low = [t.lower() for t in tokens]
    for i, tok in enumerate(low):
        if tok in UNITS or (tok == "miles" and low[i + 1:i + 3] ==
                            ["per", "hour"]):
            j, parts = i - 1, []
            while j >= 0 and len(parts) < 6 and (
                    low[j] in NUMWORDS or low[j].replace("-", "") in
                    NUMWORDS or re.fullmatch(r"\d[\d,\.]*", low[j])):
                parts.append(tokens[j])
                j -= 1
            if parts:
                unit = "miles per hour" if tok == "miles" else tokens[i]
                found.add(" ".join(reversed(parts)) + " " + unit)
    return found


def scan_text(filename: str) -> str:
    """Scan a text file for content-quality evidence — never guess.

    Returns: (1) meta/process phrase hits with line numbers — phrases a
    viewer should never hear in a finished video (talk about the research
    process, the channel, view counts, the script itself); (2) sentences
    repeated word-for-word; (3) every statistic claim in the text, so
    each one can be checked against the source material.

    Use this in a quality pass BEFORE calling a text finished.

    Args:
        filename: Name of the file inside the work folder.
    Returns:
        JSON string with the scan evidence.
    """
    path = os.path.normpath(os.path.join(WORK, filename))
    if not path.startswith(os.path.normpath(WORK) + os.sep):
        return json.dumps({"status": "error",
                           "error": "work folder-এর বাইরে যাওয়া যায় না"})
    if not os.path.exists(path):
        return json.dumps({"status": "error", "error": "file নেই"},
                          ensure_ascii=False)
    try:
        txt = open(path, encoding="utf-8").read()
        lines = txt.splitlines()
        meta = []
        for i, ln in enumerate(lines, 1):
            low = ln.lower()
            for pat in META_PATTERNS:
                if pat in low:
                    meta.append({"line": i, "pattern": pat,
                                 "text": ln.strip()[:160]})
        sentences = [s.strip() for s in
                     re.split(r"(?<=[.!?])\s+", txt) if len(s.strip()) > 25]
        dups = [s for s, c in Counter(
            re.sub(r"\s+", " ", s.lower()) for s in sentences).items()
            if c > 1]
        stats = sorted(set(m.group(0) for m in STAT_RE.finditer(txt))
                       | spelled_stats(txt))
        return json.dumps({"status": "ok", "file": filename,
                           "meta_hits": meta,
                           "duplicate_sentences": dups,
                           "statistics_found": stats},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error",
                           "error": f"{type(e).__name__}: {e}"},
                          ensure_ascii=False)


v7 = v9.v7
v7.TOOLS = v7.TOOLS + [scan_text]
v7.SCHEMAS = {**v7.SCHEMAS, scan_text: ScanArgs}
v7.TOOL_MAP = {fn.__name__: fn for fn in v7.TOOLS}
v7.SYSTEM += (
    "\n\nNEW TOOL — scan_text: কোনো লেখা 'শেষ' বলার আগে scan_text দিয়ে "
    "যাচাই করবে — meta/process কথা (দর্শকের শোনার কথা নয়), পুনরাবৃত্তি, "
    "আর প্রতিটা সংখ্যা-দাবি বের করে সূত্রের সাথে মেলাবে।")

MISSION = """QUALITY MISSION — script.md একটা "শেষ হওয়া" script (narration 705 শব্দ, সংখ্যার contract PASS)। কিন্তু বিষয়বস্তুর মান যাচাই হয়নি — তোমার কাজ সেই যাচাই আর মেরামত।

1. scan_text দিয়ে script.md scan করো, তারপর পুরো script নিজে পড়ো।
2. এই মানদণ্ডগুলোতে যাচাই করো:
   (ক) META/বিষয়ের বাইরের কথা: research প্রক্রিয়া, viewers, channel, নিজের কাজের কথা — দর্শকের জন্য বানানো video-তে এসব থাকা যাবে না।
   (খ) প্রতিটা সংখ্যা/তথ্য research_notes.md-তে আছে কিনা। না থাকলে "যাচাই করা যায়নি" বলে চিহ্নিত করবে — বানিয়ে মেলাবে না, আবার যাচাই-অযোগ্য মানেই ভুল নয়।
   (গ) একই বাক্য/ভাবের পুনরাবৃত্তি।
   (ঘ) প্রতিটা scene video-র বিষয়ের (মানব মস্তিষ্ক) সাথে মিলছে কিনা।
3. quality_report.md-তে বাংলায় লিখবে: প্রতিটা সমস্যা scene নম্বরসহ, কোন মানদণ্ডে ধরলে, আর যা যাচাই করা যায়নি তাও সৎভাবে।
4. তারপর ঠিক করা version script_fixed.md নামে লিখবে: সমস্যার অংশ বাদ বা বিষয়ের ভেতরের লেখা দিয়ে বদল; বাকি সব হুবহু একই; closing line সবার শেষে হুবহু থাকবে; নতুন কোনো সংখ্যা/তথ্য যোগ করবে না।
5. measure_file দিয়ে script_fixed.md মাপবে — 650–750-এর বাইরে হলে append_text_file দিয়ে (বিষয়ের ভেতরের বাক্য জুড়ে) ঠিক করবে, আবার মাপবে।
6. quality_report.md-এর শেষে চূড়ান্ত মাপের সংখ্যা (tool থেকে পাওয়া) আর দুই-প্রান্তের তুলনা যোগ করবে: "চূড়ান্ত narration = X শব্দ; X ≥ 650: সত্য/মিথ্যা; X ≤ 750: সত্য/মিথ্যা"।
7. shot_list.csv ও seo_package.md ছোঁবে না।"""

if __name__ == "__main__":
    if "--unit-test" in sys.argv:
        print(scan_text("script.md"))
        sys.exit(0)
    print(f"[v10] work dir: {WORK} | memory: {v7.base6.STORE.name}",
          flush=True)
    for model in v7.MODELS:
        print(f"\n=== Brain: {model} ===", flush=True)
        try:
            out = v7.run_agent(MISSION, model)
        except Exception as e:
            print(f"⚠️ {model} ব্যর্থ ({type(e).__name__}: {e}) — fallback...",
                  flush=True)
            continue
        print("\n================ V10 REPORT ================", flush=True)
        print(out, flush=True)
        break
    print("[v10] DONE", flush=True)

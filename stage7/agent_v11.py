# Agent v11 (development phase, step 6 — 2026-11-20): v10 + final gate.
# Lessons from steps 4-5: the agent's fixes dropped required elements
# (closing line, a whole scene) and its reports described the draft in
# its head instead of the file on disk. v11 adds two tools:
#   preserve_check — mechanical before/after evidence: which headers,
#     sentences and the closing line a fix dropped (or added).
#   gate_check — the built-in final gate: re-measures the FINISHED file
#     from disk (word contract, meta scan, preservation) and returns a
#     verdict block the agent must append to its report verbatim, so the
#     report's final numbers always come from the file, never from memory.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import agent_v10 as v10  # noqa: E402  (v9 + scan_text)

WORK = os.path.join(HERE, "work_complex6")
os.makedirs(WORK, exist_ok=True)
v10.WORK = WORK
v10.v9.WORK = WORK
v10.v9.v8.WORK = WORK
v10.v9.v7.WORK_DIR = WORK
v10.v9.v7.base.WORK_DIR = WORK

from pydantic import BaseModel  # noqa: E402


class PreserveArgs(BaseModel):
    before_file: str
    after_file: str


class GateArgs(BaseModel):
    original_file: str
    fixed_file: str
    min_words: int
    max_words: int


def _read(filename):
    path = os.path.normpath(os.path.join(WORK, filename))
    if not path.startswith(os.path.normpath(WORK) + os.sep):
        return None
    if not os.path.exists(path):
        return None
    return open(path, encoding="utf-8").read()


def _norm(s):
    return re.sub(r"\s+", " ", s.strip().strip("\"“”'")).lower()


def _narration_words(txt):
    lines = [ln for ln in txt.splitlines() if not ln.strip().startswith("#")]
    clean = re.sub(r"\[[^\]]*\]", " ", "\n".join(lines))
    return len(clean.split())


def _headers(txt):
    out = []
    for ln in txt.splitlines():
        s = ln.strip()
        if re.fullmatch(r"\[.+\]", s) or s.startswith("#"):
            out.append(s)
    return out


def _sentences(txt):
    parts = [s.strip() for s in re.split(r"(?<=[.!?।])\s+", txt)
             if len(s.strip()) > 25]
    return {_norm(s): s for s in parts}


def _preserve(txt_before, txt_after):
    hb = _headers(txt_before)
    ha = {_norm(h) for h in _headers(txt_after)}
    missing_headers = [h for h in hb if _norm(h) not in ha]
    nonempty = [ln for ln in txt_before.splitlines() if ln.strip()]
    closing = nonempty[-1].strip() if nonempty else ""
    closing_ok = bool(closing) and _norm(closing) in _norm(txt_after)
    sb = _sentences(txt_before)
    sa = _sentences(txt_after)
    missing = [sb[k] for k in sb if k not in sa]
    added = [sa[k] for k in sa if k not in sb]
    return {
        "missing_headers": missing_headers,
        "closing_line": closing[:160],
        "closing_line_preserved": closing_ok,
        "missing_sentences": [s[:160] for s in missing[:12]],
        "missing_count": len(missing),
        "added_sentences": [s[:160] for s in added[:6]],
        "added_count": len(added),
    }


def preserve_check(before_file: str, after_file: str) -> str:
    """Compare two files and report what the second one DROPPED or ADDED.

    Mechanical preservation evidence: scene/section headers present in
    the original but missing in the new file, whether the original's
    closing (last) line survived, and the exact sentences that vanished
    or appeared. A fix may intentionally remove bad content — this tool
    does not judge; it lists the facts so EVERY dropped item can be
    accounted for in the report (intentional + why, or restored).

    Run this after ANY rewrite/fix of an existing file, before calling
    the work finished.

    Args:
        before_file: Original file inside the work folder.
        after_file: Rewritten/fixed file inside the work folder.
    Returns:
        JSON string with the preservation evidence.
    """
    tb = _read(before_file)
    ta = _read(after_file)
    if tb is None or ta is None:
        return json.dumps({"status": "error", "error": "file নেই"},
                          ensure_ascii=False)
    out = {"status": "ok", "before": before_file, "after": after_file}
    out.update(_preserve(tb, ta))
    return json.dumps(out, ensure_ascii=False)


def gate_check(original_file: str, fixed_file: str,
               min_words: int, max_words: int) -> str:
    """THE FINAL GATE — run this LAST, on the finished file, from disk.

    Re-measures the fixed file: narration word count against the
    contract (both ends), meta/process phrase scan, and preservation
    against the original (headers, closing line, dropped sentences).
    Returns a ready-made verdict block (in `verdict_block`) that MUST
    be appended to the report word-for-word — the report's final
    numbers come from this tool, never from your own counting or from
    an earlier draft.

    Args:
        original_file: The file before fixing (work folder).
        fixed_file: The finished fixed file (work folder).
        min_words: Contract minimum narration words.
        max_words: Contract maximum narration words.
    Returns:
        JSON string with all measurements and the verdict block.
    """
    to = _read(original_file)
    tf = _read(fixed_file)
    if to is None or tf is None:
        return json.dumps({"status": "error", "error": "file নেই"},
                          ensure_ascii=False)
    x = _narration_words(tf)
    lo_ok = x >= min_words
    hi_ok = x <= max_words
    meta = []
    for i, ln in enumerate(tf.splitlines(), 1):
        low = ln.lower()
        for pat in v10.META_PATTERNS:
            if pat in low:
                meta.append({"line": i, "pattern": pat})
    pres = _preserve(to, tf)
    passed = (lo_ok and hi_ok and not meta
              and pres["closing_line_preserved"]
              and not pres["missing_headers"])
    tf_ = lambda b: "সত্য" if b else "মিথ্যা"  # noqa: E731
    block = (
        "=== GATE CHECK (tool-এর মাপা ফল) ===\n"
        f"চূড়ান্ত narration = {x} শব্দ; {x} ≥ {min_words}: {tf_(lo_ok)}; "
        f"{x} ≤ {max_words}: {tf_(hi_ok)}\n"
        f"Meta/process hit: {len(meta)}টা\n"
        f"সংরক্ষণ: closing line "
        f"{'আছে' if pres['closing_line_preserved'] else 'নেই'}; "
        f"হারানো header: "
        f"{pres['missing_headers'] if pres['missing_headers'] else 'নেই'}; "
        f"হারানো বাক্য: {pres['missing_count']}টা — report-এ প্রতিটার "
        f"হিসাব থাকতে হবে\n"
        f"GATE: {'PASS' if passed else 'FAIL'}")
    return json.dumps(
        {"status": "ok", "file": fixed_file, "narration_words": x,
         "min_words": min_words, "max_words": max_words,
         "lower_ok": lo_ok, "upper_ok": hi_ok, "meta_hits": meta,
         "preservation": pres, "gate_pass": passed,
         "verdict_block": block},
        ensure_ascii=False)


v7 = v10.v7
v7.TOOLS = v7.TOOLS + [preserve_check, gate_check]
v7.SCHEMAS = {**v7.SCHEMAS, preserve_check: PreserveArgs,
              gate_check: GateArgs}
v7.TOOL_MAP = {fn.__name__: fn for fn in v7.TOOLS}
v7.SYSTEM += (
    "\n\nFINAL GATE নিয়ম (v11): কোনো file ঠিক/পুনর্লিখন করলে কাজ শেষ "
    "বলার আগে (১) preserve_check দিয়ে দেখবে মূল file-এর কোন header, "
    "বাক্য বা closing line হারিয়েছে — প্রতিটার হিসাব report-এ দেবে "
    "(ইচ্ছাকৃত বাদ হলে কারণসহ, নইলে ফিরিয়ে আনবে); (২) gate_check "
    "চালিয়ে তার verdict_block report-এর শেষে হুবহু append করবে। "
    "Report-এর কোনো সংখ্যা নিজের মাথা থেকে বা আগের draft থেকে লিখবে "
    "না — সব সংখ্যা file মেপে tool থেকে আসবে।")

if __name__ == "__main__":
    if "--unit-test" in sys.argv:
        print(preserve_check("script.md", "script_fixed.md"))
        print(gate_check("script.md", "script_fixed.md", 650, 750))
        sys.exit(0)
    print("[v11] library module — run via a mission runner.")

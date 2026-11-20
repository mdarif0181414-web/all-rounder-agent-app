# Agent v12 (development phase, step 7 — 2026-11-20): v11 + lesson memory.
# The agent already had remember/recall for FACTS (Stage 5). Lessons are
# different: working RULES learned from its own verified missions
# ("after fixing a file, run preserve_check before calling it done —
# because a fix once dropped the closing line"). v12 adds:
#   save_lesson   — store a rule in long-term memory, tagged LESSON.
#   recall_lessons — pull back the rules relevant to a new task.
# Plus a SYSTEM discipline: recall lessons at mission start, save the
# mission's lesson after a successful (gate-passed) finish. Lessons live
# in the same store as facts (local JSON in the workshop; Supabase in
# the hosted app) and survive across sessions.
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import agent_v11 as v11  # noqa: E402  (v10 + preserve/gate tools)

WORK = os.path.join(HERE, "work_lesson_a")
v7 = v11.v7
base = v7.base  # agent_v4 (file tools' work dir)
mem = v7.base6  # agent_v6: STORE, embed, remember


def set_work(path):
    """Point every layer's file-work dir at `path` (memory store is
    bound at v6 import and does NOT move — lessons persist)."""
    global WORK
    WORK = path
    os.makedirs(path, exist_ok=True)
    v11.WORK = path
    v11.v10.WORK = path
    v11.v10.v9.WORK = path
    v11.v10.v9.v8.WORK = path
    v7.WORK_DIR = path
    base.WORK_DIR = path


set_work(WORK)

from pydantic import BaseModel  # noqa: E402


class SaveLessonArgs(BaseModel):
    lesson: str


class RecallLessonsArgs(BaseModel):
    topic: str


LESSON_SOURCE = "LESSON — agent self-learning, 2026-11-20"


def save_lesson(lesson: str) -> str:
    """Save a working RULE you learned from a finished mission.

    Lessons are not facts about the world — they are rules for how YOU
    should work, each with its reason, e.g. "কোনো file fix করার পর
    preserve_check না চালিয়ে কাজ শেষ বলবে না — কারণ একবার fix-এ
    closing line হারিয়ে গিয়েছিল।" Keep it to one or two sentences:
    the rule + why. Save only after the mission truly succeeded
    (final gate PASS); a lesson from a failed attempt teaches the
    wrong thing. Stored in long-term memory and recalled in future
    missions, across sessions.

    Args:
        lesson: The rule, phrased so it makes sense on its own.
    Returns:
        JSON string with the stored lesson id.
    """
    lesson = lesson.strip()
    if len(lesson) < 20:
        return json.dumps({"status": "error",
                           "error": "পাঠ খুব ছোট — নিয়ম + কারণ লিখতে হবে"},
                          ensure_ascii=False)
    return mem.remember(lesson, LESSON_SOURCE)


def recall_lessons(topic: str) -> str:
    """Recall the working RULES (lessons) relevant to a task.

    Call this at the START of every mission, before doing the work,
    with a short description of the task type (e.g. "script fix quality
    check"). Returns the lessons your earlier missions saved. Follow
    them — they were bought with real mistakes.

    Args:
        topic: Short description of the task you are about to do.
    Returns:
        JSON string with the matching lessons.
    """
    try:
        vec = mem.embed(topic + " lesson rule how to work",
                         "RETRIEVAL_QUERY")
        hits = mem.STORE.search(vec, limit=10)
        lessons = [h for h in hits
                   if str(h.get("source", "")).startswith("LESSON")]
        if not lessons and getattr(mem.STORE, "rows", None):
            lessons = [{"content": r["content"], "source": r["source"]}
                       for r in mem.STORE.rows
                       if str(r.get("source", "")).startswith("LESSON")]
        return json.dumps({"status": "ok", "backend": mem.STORE.name,
                           "lessons": lessons[:5],
                           "count": min(len(lessons), 5)},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error",
                           "error": f"{type(e).__name__}: {e}"},
                          ensure_ascii=False)


v7.TOOLS = v7.TOOLS + [save_lesson, recall_lessons]
v7.SCHEMAS = {**v7.SCHEMAS, save_lesson: SaveLessonArgs,
              recall_lessons: RecallLessonsArgs}
v7.TOOL_MAP = {fn.__name__: fn for fn in v7.TOOLS}
v7.SYSTEM += (
    "\n\nLESSON MEMORY নিয়ম (v12): (১) প্রতিটা mission-এর শুরুতেই "
    "recall_lessons দিয়ে কাজের ধরন অনুযায়ী আগের পাঠ মনে করবে এবং "
    "সেই নিয়মগুলো মেনে চলবে। (২) Mission সফল হলে (final gate PASS) "
    "save_lesson দিয়ে এই mission-এর সবচেয়ে গুরুত্বপূর্ণ পাঠটা "
    "নিয়মের আকারে জমা দেবে — কী করতে হবে + কেন, এক-দুই বাক্যে। "
    "সাধারণ তথ্য (fact) পাঠ হিসেবে জমা দেবে না।")

if __name__ == "__main__":
    if "--check" in sys.argv:  # not "--unit-test": v8 skips key load on it
        print("store backend:", mem.STORE.name)
        print("store path:", getattr(mem.STORE, "path", "(supabase)"))
        print("rows before:", mem.STORE.count())
        print("tools:", "save_lesson" in v7.TOOL_MAP,
              "recall_lessons" in v7.TOOL_MAP)
        print(recall_lessons("script fix quality check"))
        sys.exit(0)
    print("[v12] library module — run via a mission runner.")

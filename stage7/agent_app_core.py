# Stage 7 app core: agent v7/v6-কে programmatic ভাবে চালানোর layer।
# Env (GEMINI_API_KEY ইত্যাদি) import-এর আগেই set থাকতে হবে — app.py /
# launcher-এর দায়িত্ব। Key কখনো এই file-এ থাকে না (A3)।
import csv
import io
import json
import os
import re

import agent_v13 as v13  # dev-phase tools (v8–v13) patch v7 at import
v7 = v13.v7
from google.genai import types

BASE6 = v7.base6
STORE = BASE6.STORE
WORK_DIR = v7.WORK_DIR


def memory_stats() -> dict:
    try:
        count = STORE.count()
    except Exception:
        count = -1
    return {"count": count, "backend": type(STORE).__name__}


def recall(query: str, top_k: int = 5) -> list:
    raw = BASE6.recall_memories(query=query, limit=top_k)
    try:
        return json.loads(raw).get("results", [])
    except Exception:
        return []


def _gen_text(prompt: str) -> str:
    config = types.GenerateContentConfig(
        system_instruction=v7.SYSTEM, temperature=0.4)
    contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]
    last_err = None
    for model in BASE6.MODELS:
        try:
            resp = BASE6._gen(model, contents, config)
            return "".join(p.text for p in resp.candidates[0].content.parts
                           if getattr(p, "text", None)).strip()
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"সব model ব্যর্থ: {last_err}")


# --- Chat (A1 speed fix, 2026-11-20) -------------------------------------
# আগের পথে উত্তর ৫–১০ মিনিট লাগত: _gen প্রতিটা model-এ ২ বার retry +
# 60s timeout — model overload-এ সময় গুণ হয়ে যেত। এখন: দ্রুততম model
# আগে, প্রতিটায় মাত্র ১টা চেষ্টা, আর streaming — উত্তর শব্দ ধরে ধরে আসে।
CHAT_MODELS = list(reversed(BASE6.MODELS))  # flash-lite → 3.5 → 3.8
CHAT_SYSTEM = (
    "তুমি All-Rounder Agent — ব্যবহারকারীর নিজের autonomous AI agent। "
    "সংক্ষেপে, পরিষ্কারভাবে উত্তর দাও। memory থেকে তথ্য ব্যবহার করলে "
    "[সূত্র: ...] আকারে সূত্র দাও। যা জানো না, সৎভাবে বলো — বানাবে না। "
    "ব্যবহারকারী যে ভাষায় লিখেছে, সেই ভাষায় উত্তর দাও।")


def _chat_prompt(question: str) -> str:
    results = recall(question)
    if results:
        ctx = "\n".join(f"- {r.get('content', '')} [সূত্র: {r.get('source', '')}]"
                        for r in results)
        mem_block = f"তোমার long-term memory থেকে পাওয়া তথ্য:\n{ctx}"
    else:
        mem_block = "তোমার long-term memory-তে এই প্রশ্নের প্রাসঙ্গিক কিছু নেই।"
    return (
        f"{mem_block}\n\nব্যবহারকারীর প্রশ্ন: {question}\n\n"
        "নিয়ম: memory-র তথ্য ব্যবহার করলে উত্তরে [সূত্র: ...] আকারে সূত্র "
        "দেবে (A6)। memory-তে না থাকলে সৎভাবে বলবে জানো না — বানাবে না। "
        "ব্যবহারকারী যে ভাষায় প্রশ্ন করেছে সেই ভাষায় উত্তর দেবে।")


def chat_answer_stream(question: str):
    """Streaming chat উত্তর — token আসার সাথে সাথে yield করে।
    এক model ব্যর্থ হলে পরেরটা; সব ব্যর্থ হলে ভদ্র বাংলা error।"""
    prompt = _chat_prompt(question)
    config = types.GenerateContentConfig(
        system_instruction=CHAT_SYSTEM, temperature=0.4)
    contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]
    for model in CHAT_MODELS:
        yielded = False
        try:
            stream = BASE6.client().models.generate_content_stream(
                model=model, contents=contents, config=config)
            for chunk in stream:
                if getattr(chunk, "text", None):
                    yielded = True
                    yield chunk.text
            if yielded:
                return
        except Exception:
            if yielded:
                yield "\n\n⚠️ (উত্তরের মাঝে সংযোগ বিচ্ছিন্ন হয়েছে — আবার চেষ্টা করো)"
                return
            continue
    yield ("⚠️ এখন সব brain-ই ব্যস্ত/অধিগম্য নয় (free tier-এর ভিড়)। "
           "একটু পরে আবার চেষ্টা করো।")


def chat_answer(question: str) -> str:
    return "".join(chat_answer_stream(question))


def build_mission(brief: str) -> str:
    return (
        f"তুমি একজন faceless YouTube video production agent। Client brief:\n"
        f"\"\"\"{brief}\"\"\"\n\n"
        "ধাপে ধাপে কাজ করবে:\n"
        "1. প্রথমে recall_memories অন্তত ২টি query দিয়ে চালাবে — প্রাসঙ্গিক "
        "পাঠ থাকলে সূত্রসহ ব্যবহার করবে, না থাকলে সৎভাবে বলবে।\n"
        "2. brief-এর বিষয়ের জন্য ৩টি candidate niche/topic angle ঠিক করে "
        "প্রতিটার youtube_search (৫ ফলাফল) চালাবে। শুধু tool-এর আসল ফলাফলই "
        "ব্যবহার করবে — কোনো সংখ্যা বানাবে না।\n"
        "3. আসল view প্রমাণে winner বাছবে, তারপর ঠিক এই ৫টি deliverable "
        "write_text_file দিয়ে বানাবে:\n"
        "   - research_notes.md: আসল titles/channels/views, niche সিদ্ধান্ত "
        "+ সংখ্যার প্রমাণ, memory পাঠ সূত্রসহ বা সৎ 'নেই'।\n"
        "   - script.md: English narration 150–210 শব্দ, প্রথম বাক্যে hook, "
        "[Scene N] markers, শেষে soft subscribe line।\n"
        "   - shot_list.csv: header scene,script_line,visual_prompt,"
        "duration_sec; সব prompt-এ একই style 'cinematic, photorealistic, "
        "dramatic lighting'; মোট duration 60–90 সেকেন্ড।\n"
        "   - seo_package.md: ৫টি title option /100 score-সহ (hook 30, "
        "curiosity 25, clarity 25, searchability 20), winner = final title, "
        "~120 শব্দের description, ঠিক ৩টি hashtag, thumbnail brief।\n"
        "   - demo_report.md: বাংলায় — কী বানালে, niche প্রমাণ এক লাইনে, "
        "memory ব্যবহার সূত্রসহ, ROI অনুমান (অনুমান বলে চিহ্নিত; agent-এর "
        "সময় নিয়ে সংখ্যা বানাবে না), human QC checklist।\n"
        "4. শেষে প্রতিটি file read_text_file দিয়ে যাচাই করবে।")


def run_produce(brief: str, log=None) -> dict:
    """Produce mission চালিয়ে {report, files, checks} ফেরত দেয়।"""
    def note(msg):
        if log:
            log(msg)

    config = types.GenerateContentConfig(
        tools=v7.TOOLS, system_instruction=v7.SYSTEM, temperature=0.4,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            disable=True))
    mission = build_mission(brief)
    last_err = None
    for model in BASE6.MODELS:
        note(f"Brain: {model}")
        try:
            contents = [types.Content(
                role="user", parts=[types.Part(text=mission)])]
            final = ""
            for step in range(1, 31):
                resp = BASE6._gen(model, contents, config)
                cand = resp.candidates[0]
                contents.append(cand.content)
                calls = [p for p in cand.content.parts
                         if getattr(p, "function_call", None)]
                if not calls:
                    final = "".join(
                        p.text for p in cand.content.parts
                        if getattr(p, "text", None)).strip()
                    break
                parts = []
                for p in calls:
                    fc = p.function_call
                    fn = v7.TOOL_MAP.get(fc.name)
                    note(f"step {step}: {fc.name}")
                    try:
                        clean = v7.SCHEMAS[fn].model_validate(
                            dict(fc.args or {})).model_dump()
                        result = fn(**clean)
                    except Exception as e:
                        result = json.dumps(
                            {"status": "error",
                             "error": f"{type(e).__name__}: {e}"},
                            ensure_ascii=False)
                    parts.append(types.Part.from_function_response(
                        name=fc.name, response={"result": result}))
                contents.append(types.Content(role="user", parts=parts))
            files = _collect_files()
            return {"report": final, "files": files,
                    "checks": contract_check(files), "brain": model}
        except Exception as e:
            last_err = e
            note(f"{model} ব্যর্থ — fallback")
            continue
    raise RuntimeError(f"সব model ব্যর্থ: {last_err}")


def _collect_files() -> dict:
    out = {}
    for name in ("research_notes.md", "script.md", "shot_list.csv",
                 "seo_package.md", "demo_report.md"):
        p = os.path.join(WORK_DIR, name)
        if os.path.exists(p):
            out[name] = open(p, encoding="utf-8").read()
    return out


def contract_check(files: dict) -> dict:
    """Deliverable contract-এর যান্ত্রিক যাচাই — Colab run-এর শিক্ষা থেকে:
    agent-এর নিজের দাবি নয়, মাপা সংখ্যাই এখানে সত্য।"""
    checks = {}
    checks["৫টি file আছে"] = len(files) == 5
    s = files.get("script.md", "")
    if s:
        body = s.split("---", 1)[1] if "---" in s else s
        body = re.sub(r"\[Scene \d+\]", "", body)
        body = re.sub(r"^#.*$", "", body, flags=re.M)
        words = len([w for w in body.split() if any(c.isalnum() for c in w)])
        checks[f"script 150–210 শব্দ (মাপা: {words})"] = 150 <= words <= 210
    raw = files.get("shot_list.csv", "")
    if raw:
        try:
            rows = list(csv.DictReader(io.StringIO(raw)))
            total = sum(float(r["duration_sec"]) for r in rows)
            checks[f"shot list মোট 60–90s (মাপা: {total:.0f}s, "
                   f"{len(rows)} scene)"] = 60 <= total <= 90 and len(rows) >= 5
        except Exception:
            checks["shot list CSV পড়া যায়"] = False
    seo = files.get("seo_package.md", "")
    if seo:
        tags = re.findall(r"#\w+", seo)
        checks[f"ঠিক ৩টি hashtag (মাপা: {len(tags)})"] = len(tags) == 3
    res = files.get("research_notes.md", "")
    if res:
        checks["research-এ আসল view সংখ্যা আছে"] = bool(
            re.search(r"\d+(\.\d+)?[MK]\s*views|\d+(\.\d+)?[MK]\b", res))
    return checks

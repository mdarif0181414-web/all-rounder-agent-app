# Stage 6 — Vertical: Content/Media Production Pipeline (agent v7)
# ---------------------------------------------------------------
# v6 (ReAct + Stage 2 gate + browser + Supabase memory)-এর ওপর production
# specialization: একটা client-style brief পেলে agent নিজে YouTube research
# করে পূর্ণ Faceless Video Production Package বানায় — research notes,
# script, shot list, SEO package, আর শেষে ROI demo report।
#
# Stage 4-এর শিক্ষা অনুযায়ী deliverable contract এখানে PIN করা — model
# শুধু contract পূরণ করে, নিজে থেকে file/কাঠামো বদলাতে পারে না।
# Addendum B1: প্রথম client ব্যবহারকারী নিজে — এই package-টাই তার
# Fiverr Gig 1 (AI faceless video)-এর demo/sample হিসেবে যাবে।
#
# ব্যবহার: python3 agent_v7.py produce

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.path.join(HERE, "work_produce")
os.makedirs(WORK_DIR, exist_ok=True)

sys.path.insert(0, HERE)
import agent_v6 as base6  # noqa: E402

base = base6.base  # agent_v4
base.WORK_DIR = WORK_DIR  # write/read tools এই folder-এই বন্দী

from google.genai import types  # noqa: E402

MODELS = base6.MODELS
_gen = base6._gen


def youtube_search(keyword: str, max_results: int = 5) -> str:
    """Search YouTube in a real browser and return structured results.

    v7 wrapper around the Stage 3 tool: the sandbox relay route is flaky
    (a timed-out page.goto leaves the shared page poisoned and the next
    searches fail with it), so on error the shared browser is fully reset
    and the search retried, up to 3 attempts.

    Args:
        keyword: The search phrase, e.g. 'space facts'.
        max_results: How many top videos to return (default 5).
    Returns:
        JSON string: a list of {title, channel, views, age} — or an error.
    """
    last = ""
    for attempt in range(3):
        result = base.youtube_search(keyword, max_results)
        try:
            ok = json.loads(result).get("status") == "ok"
        except Exception:
            ok = False
        if ok:
            return result
        last = result
        try:
            b = base._BROWSER
            if b.get("browser"):
                b["browser"].close()
            if b.get("pw"):
                b["pw"].stop()
        except Exception:
            pass
        base._BROWSER.clear()
        time.sleep(5)
    return last


TOOLS = [base6.remember, base6.recall_memories,
         youtube_search, base.browser_open, base.fetch_web_page,
         base.write_text_file, base.read_text_file]
SCHEMAS = {base6.remember: base6.RememberArgs,
           base6.recall_memories: base6.RecallArgs,
           youtube_search: base.YoutubeSearchArgs,
           base.browser_open: base.BrowserOpenArgs,
           base.fetch_web_page: base.FetchArgs,
           base.write_text_file: base.WriteArgs,
           base.read_text_file: base.ReadArgs}
TOOL_MAP = {fn.__name__: fn for fn in TOOLS}

SYSTEM = (
    "You are a content-production agent for a small agency. You turn a client "
    "brief into a complete, ready-to-produce faceless YouTube video package. "
    "Hard rules: (1) Every number you report (views, counts) must come from a "
    "tool result in this session — never invent or round from memory. "
    "(2) Deliverables are pinned by the mission: exact filenames, exact "
    "sections. Do not rename, skip or merge them. (3) First recall long-term "
    "memory for production lessons; use what is genuinely relevant and cite "
    "its source like [সূত্র: ...]; if little is relevant, say so honestly. "
    "(4) Write files with write_text_file, then read the main ones back to "
    "verify before finishing. (5) Your final message is a short Bengali "
    "summary of what was produced and what a human must still check."
)

BRIEF = (
    "CLIENT BRIEF (demo client — a small online education channel):\n"
    "- Faceless YouTube channel, English narration, audience: curious adults "
    "and older teens (USA/UK).\n"
    "- Wants ONE video package: a 60–90 second faceless explainer video.\n"
    "- Candidate niches (research all three, then YOU pick the strongest): "
    "(a) space facts, (b) history mysteries, (c) amazing animal facts.\n"
    "- Pick by evidence: use youtube_search on each niche (5 results each); "
    "the niche whose recent videos show the strongest real view counts wins. "
    "State the evidence for your pick in research_notes.md.\n"
    "- Then produce the full package for ONE video in the winning niche."
)

PRODUCE_MISSION = (
    BRIEF
    + "\n\nDELIVERABLES — ঠিক এই ৫টি file, এই ক্রমে বানাবে:\n"
    "1. research_notes.md — প্রতিটা niche-এর জন্য: পাওয়া video গুলোর আসল "
    "title, channel, views (tool result থেকে হুবহু); তারপর কোন niche জিতল "
    "এবং কেন (সংখ্যার প্রমাণসহ); শেষে memory থেকে recall করা প্রাসঙ্গিক "
    "পাঠ থাকলে সূত্রসহ [সূত্র: ...], না থাকলে সৎভাবে 'প্রাসঙ্গিক স্মৃতি "
    "পাওয়া যায়নি'। শুরুতে recall_memories দিয়ে অন্তত দুইভাবে খুঁজবে "
    "(যেমন 'YouTube niche research lessons' ও 'video production rules')।\n"
    "2. script.md — জেতা niche-এ একটা video-র পূর্ণ English narration "
    "script: মোট 150–210 শব্দ (60–90 সেকেন্ড); প্রথম বাক্যেই hook "
    "(৫ সেকেন্ডের মধ্যে কৌতূহল); [Scene 1], [Scene 2]... marker দিয়ে "
    "ভাগ করা; শেষে subscribe-এর এক লাইনের soft call।\n"
    "3. shot_list.csv — header: scene,script_line,visual_prompt,duration_sec "
    "— প্রতিটা scene-এর জন্য এক row: script-এর সংশ্লিষ্ট অংশ, generation-"
    "ready English visual prompt (সব prompt-এ একই style ধারা: 'cinematic, "
    "photorealistic, dramatic lighting'), আনুমানিক duration; মোট duration "
    "60–90 সেকেন্ডের মধ্যে রাখবে।\n"
    "4. seo_package.md — ৫টি title option, প্রতিটা /100 score-সহ "
    "(hook 30, curiosity 25, clarity 25, searchability 20 — কোনটায় কত, "
    "তাও লিখবে); সর্বোচ্চ score-এর title-টাই final; ~120 শব্দের English "
    "description; ঠিক ৩টি hashtag; thumbnail concept brief (একটা বড় "
    "focal point, সর্বোচ্চ ৩ শব্দের লেখা)।\n"
    "5. demo_report.md — বাংলায়: কী কী বানালে; niche সিদ্ধান্তের প্রমাণ "
    "এক লাইনে; memory থেকে কী ব্যবহার করলে (সূত্রসহ) বা সৎ স্বীকারোক্তি; "
    "মানুষের হাতে এই package বানাতে আনুমানিক কত সময় লাগত বনাম agent-এর "
    "সময় (ROI হিসাব — অনুমান বলে চিহ্নিত করবে); human QC checklist "
    "(কোন তথ্য/সংখ্যা মানুষ আবার যাচাই করবে); শেষে client-কে দেখানোর "
    "মতো এক লাইনের English ROI বাক্য।\n\n"
    "সব file write_text_file দিয়ে লিখবে; শেষে script.md ও seo_package.md "
    "read_text_file দিয়ে পড়ে যাচাই করবে। কোনো search ব্যর্থ হলে সেটা "
    "notes-এ সৎভাবে লিখে বাকি niche দিয়ে এগিয়ে যাবে — থামবে না।"
)


def run_agent(mission: str, model: str) -> str:
    config = types.GenerateContentConfig(
        tools=TOOLS, system_instruction=SYSTEM, temperature=0.4,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    contents = [types.Content(role="user", parts=[types.Part(text=mission)])]
    for step in range(1, 31):
        resp = _gen(model, contents, config)
        cand = resp.candidates[0]
        contents.append(cand.content)
        calls = [p for p in cand.content.parts if getattr(p, "function_call", None)]
        if not calls:
            return "".join(p.text for p in cand.content.parts
                           if getattr(p, "text", None)).strip()
        parts = []
        for p in calls:
            fc = p.function_call
            fn = TOOL_MAP.get(fc.name)
            print(f"  🔧 step {step}: {fc.name}")
            if fn is None:
                result = json.dumps({"status": "error",
                                     "error": f"unknown tool {fc.name}"})
            else:
                try:
                    clean = SCHEMAS[fn].model_validate(dict(fc.args or {})).model_dump()
                    result = fn(**clean)
                except Exception as e:
                    result = json.dumps({"status": "error",
                                         "error": f"{type(e).__name__}: {e}"},
                                        ensure_ascii=False)
            print(f"  👁  -> {result[:200]}")
            parts.append(types.Part.from_function_response(
                name=fc.name, response={"result": result}))
        contents.append(types.Content(role="user", parts=parts))
    return "(ধাপের সীমা শেষ)"


def main():
    print(f"[Stage 6 agent v7 — mode: produce | memory backend: {base6.STORE.name} "
          f"| work dir: {WORK_DIR}]")
    for model in MODELS:
        print(f"\n=== Brain: {model} ===")
        try:
            out = run_agent(PRODUCE_MISSION, model)
        except Exception as e:
            print(f"⚠️ {model} ব্যর্থ ({type(e).__name__}: {e}) — fallback...")
            continue
        print("\n================ PRODUCE REPORT ================")
        print(out)
        return
    print("সব model ব্যর্থ")


if __name__ == "__main__":
    main()

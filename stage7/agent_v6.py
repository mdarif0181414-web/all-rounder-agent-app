# Stage 5 — Persistent Memory (agent v6)
# ---------------------------------------------------------------
# Stage 1-এর ReAct loop + Stage 2-এর gate (agent_v4 থেকে) + নতুন ক্ষমতা:
# long-term memory। remember() দিয়ে তথ্য Supabase pgvector-এ জমা হয়
# (Gemini embedding, 768 dim), recall_memories() দিয়ে অর্থ মিলিয়ে খুঁজে
# আনা যায় — অন্য session, এমনকি অন্য process থেকেও।
#
# ব্যবহার: python3 agent_v6.py learn   → session 1: তথ্য শেখে (memory-তে রাখে)
#          python3 agent_v6.py ask     → session 2: শুধু memory থেকে উত্তর দেয়
# প্রমাণের প্রাণ: দুটি সম্পূর্ণ আলাদা process — ask চালানোর সময় learn-এর
# কোনো state থাকে না; উত্তর এলে তা এসেছে শুধু স্থায়ী memory থেকে।
# A6 নিয়ম: memory থেকে উত্তরে source citation বাধ্যতামূলক; না পেলে "নেই" বলা।

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.path.join(HERE, "work")
os.makedirs(WORK_DIR, exist_ok=True)

sys.path.insert(0, os.path.join(HERE, "..", "stage3"))
sys.path.insert(0, HERE)
import agent_v4 as base  # noqa: E402
import memory_store  # noqa: E402

base.WORK_DIR = WORK_DIR

from google import genai  # noqa: E402
from google.genai import types  # noqa: E402
from pydantic import BaseModel  # noqa: E402

MODELS = base.MODELS
CLIENT = None
STORE = memory_store.open_store(os.path.join(WORK_DIR, "local_memories.json"))


def client() -> genai.Client:
    global CLIENT
    if CLIENT is None:
        CLIENT = genai.Client(
            api_key=os.environ.get("GEMINI_API_KEY"),
            http_options=types.HttpOptions(api_version="v1beta", timeout=60_000))
    return CLIENT


def _gen(model, contents, config):
    last = None
    for attempt in range(2):
        try:
            return client().models.generate_content(model=model, contents=contents,
                                                    config=config)
        except Exception as e:
            last = e
            if attempt == 0:
                time.sleep(6)
    raise last


def embed(text: str, task_type: str) -> list:
    r = client().models.embed_content(
        model="gemini-embedding-001", contents=text,
        config=types.EmbedContentConfig(output_dimensionality=768,
                                        task_type=task_type))
    return list(r.embeddings[0].values)


# ---------------- memory tools ----------------

def remember(content: str, source: str) -> str:
    """Store a fact in long-term memory so it can be recalled in future sessions.

    Args:
        content: The fact to remember, as a complete standalone statement.
        source: Where this fact came from (used later as the citation).
    Returns:
        JSON string with the stored memory id.
    """
    try:
        vec = embed(content, "RETRIEVAL_DOCUMENT")
        rid = STORE.add(content, source, vec)
        return json.dumps({"status": "ok", "id": rid, "backend": STORE.name},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"},
                          ensure_ascii=False)


def recall_memories(query: str, limit: int = 5) -> str:
    """Search long-term memory by meaning and return the closest stored facts.

    Args:
        query: What to look for, phrased as a question or description.
        limit: Maximum number of memories to return (default 5).
    Returns:
        JSON string: matching memories with their source and similarity score.
        ALWAYS cite the source of any memory you use in an answer.
    """
    try:
        vec = embed(query, "RETRIEVAL_QUERY")
        hits = STORE.search(vec, limit=limit)
        return json.dumps({"status": "ok", "backend": STORE.name, "results": hits},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"},
                          ensure_ascii=False)


class RememberArgs(BaseModel):
    content: str
    source: str


class RecallArgs(BaseModel):
    query: str
    limit: int = 5


TOOLS = [remember, recall_memories, base.write_text_file, base.read_text_file]
SCHEMAS = {remember: RememberArgs, recall_memories: RecallArgs,
           base.write_text_file: base.WriteArgs, base.read_text_file: base.ReadArgs}
TOOL_MAP = {fn.__name__: fn for fn in TOOLS}

SYSTEM = (
    "You are an autonomous agent with a persistent long-term memory. "
    "Facts stored with remember() survive across sessions; recall_memories() "
    "searches that memory by meaning. Rules: (1) When asked to learn facts, "
    "store each one separately with its given source. (2) When answering "
    "questions in ask mode, FIRST search memory with recall_memories, and "
    "answer ONLY from what it returns — always name the source of each fact "
    "you use, like [সূত্র: ...]. (3) If memory has nothing relevant "
    "(similarity low or results off-topic), say plainly in Bengali that the "
    "information is not in your memory — never invent an answer."
)

FACTS = [
    ("All-Rounder Agent is a generalist autonomous AI agent built stage "
     "by stage: ReAct reasoning core, safe code execution, Playwright "
     "browser control, LangGraph multi-agent orchestration, and "
     "Supabase pgvector long-term memory.",
     "Agent project record"),
    ("The agent's production studio creates faceless video packages: "
     "research notes, a 150-210 word narration script, a shot list, an "
     "SEO package with exactly 3 hashtags, and a Bengali demo report.",
     "Stage 6 production spec"),
    ("The agent answers from its long-term memory only with sources "
     "cited; if a fact is not in memory it says so honestly instead of "
     "inventing one.",
     "Memory citation rule (A6)"),
]

LEARN_MISSION = (
    "তোমার long-term memory-তে নিচের তথ্যগুলো একে একে remember tool দিয়ে রাখো — "
    "প্রতিটা তথ্য আলাদা করে, তার source-সহ হুবহু যেভাবে দেওয়া আছে:\n\n"
    + "\n".join(f"{i+1}. তথ্য: {c}\n   source: {s}" for i, (c, s) in enumerate(FACTS))
    + "\n\nসব রাখা হলে জানাও কয়টি তথ্য রাখলে।"
)

QUESTIONS = [
    "What can the production studio create?",
    "What are the stages of the All-Rounder Agent project?",
    "What is my car's color?",
]

ASK_MISSION = (
    "নিচের প্রশ্নগুলোর উত্তর দাও। প্রতিটি প্রশ্নের জন্য আগে recall_memories দিয়ে "
    "তোমার memory খোঁজো, তারপর শুধু সেখান থেকে পাওয়া তথ্য দিয়ে বাংলায় উত্তর দাও — "
    "প্রতিটি উত্তরে তথ্যের সূত্র [সূত্র: ...] আকারে উল্লেখ করবে। কোনো প্রশ্নের উত্তর "
    "memory-তে না পেলে স্পষ্ট করে বলবে যে এই তথ্য তোমার স্মৃতিতে নেই — বানিয়ে বলবে না। "
    "সব উত্তর একসাথে 'session2_answers.md' file-এও লিখে রাখো।\n\n"
    + "\n".join(f"{i+1}. {q}" for i, q in enumerate(QUESTIONS))
)


def run_agent(mission: str, model: str) -> str:
    config = types.GenerateContentConfig(
        tools=TOOLS, system_instruction=SYSTEM, temperature=0.3,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    contents = [types.Content(role="user", parts=[types.Part(text=mission)])]
    for step in range(1, 16):
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
    mode = sys.argv[1] if len(sys.argv) > 1 else "learn"
    mission = LEARN_MISSION if mode == "learn" else ASK_MISSION
    print(f"[Stage 5 agent v6 — session mode: {mode} | memory backend: {STORE.name} "
          f"| stored memories: {STORE.count()}]")
    for model in MODELS:
        print(f"\n=== Brain: {model} ===")
        try:
            out = run_agent(mission, model)
        except Exception as e:
            print(f"⚠️ {model} ব্যর্থ ({type(e).__name__}: {e}) — fallback...")
            continue
        print(f"\n================ SESSION ({mode}) REPORT ================")
        print(out)
        return
    print("সব model ব্যর্থ")


if __name__ == "__main__":
    main()

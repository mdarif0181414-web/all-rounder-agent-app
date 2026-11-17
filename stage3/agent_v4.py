# Stage 3 — Autonomous Browser Control (agent v4)
# ---------------------------------------------------------------
# Stage 1-এর ReAct loop + Stage 2-এর শক্তকরণ (typed schema, permission gate,
# hardened execution) — তার ওপর Stage 3-এর নতুন হাত: সত্যিকারের browser (Playwright)।
#   (১) Browser tools নির্দিষ্ট কাজের (fixed-function) — model নিজে JavaScript
#       লিখে চালাতে পারে না; তাই browser ধাপে gate-এর বাইরে যাওয়ার পথ নেই।
#   (২) youtube_search — YouTube search page থেকে structured data (title, channel,
#       views) তোলে; browser_open — যেকোনো public page পড়ে; browser_screenshot —
#       চোখে দেখা প্রমাণ সংরক্ষণ করে।
#   (৩) এই browser কখনো login করে না — কোনো profile/cookie সংরক্ষিত হয় না;
#       login/OTP মানুষের হাতেই থাকে (plan-এর স্থায়ী নিয়ম)।
# Sandbox নোট: এই VM-এর egress proxy Chromium-এর CONNECT policy দিয়ে আটকায় —
# তাই এখানে AGENT_BROWSER_PROXY=http://127.0.0.1:18080 (local relay) লাগে;
# Colab-এ সরাসরি egress, কোনো proxy লাগে না।
#
# অনুমতির ধরন (env STAGE2_APPROVAL): deny (default) | grant | ask (Colab-এ input())

import ast
import json
import os
import subprocess
import sys

import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

WORK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "work")
os.makedirs(WORK_DIR, exist_ok=True)
APPROVAL_MODE = os.environ.get("STAGE2_APPROVAL", "deny")

MODELS = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-flash-lite-latest"]  # A2 routing
MAX_STEPS = 24


# ---------------- Typed schemas (A1) ----------------

class FetchArgs(BaseModel):
    url: str


class RunCodeArgs(BaseModel):
    code: str


class ReadArgs(BaseModel):
    filename: str


class WriteArgs(BaseModel):
    filename: str
    content: str


class YoutubeSearchArgs(BaseModel):
    keyword: str
    max_results: int = 5


class BrowserOpenArgs(BaseModel):
    url: str


class ScreenshotArgs(BaseModel):
    filename: str


# ---------------- Permission gate ----------------

BLOCKED_IMPORTS = {"subprocess", "socket", "ctypes", "pty", "multiprocessing", "signal"}
BLOCKED_CALLS = {"eval", "exec", "compile", "__import__",
                 "os.system", "os.popen", "os.execv", "os.execve", "os.execvp",
                 "os.spawnl", "os.spawnlp", "os.spawnle", "os.kill", "os.fork"}
APPROVAL_IMPORTS = {"requests", "urllib", "http.client", "ftplib", "smtplib", "shutil"}
APPROVAL_CALLS = {"os.remove", "os.unlink", "os.rmdir", "os.rename",
                  "pathlib.Path.unlink", "pathlib.Path.rmdir", "pathlib.Path.rename",
                  "shutil.rmtree", "shutil.move", "input"}


def _dotted(node):
    """Attribute/Name node থেকে 'os.remove' জাতীয় নাম বানায়।"""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def classify_code(code: str) -> tuple[str, list[str]]:
    """code-কে (level, reasons)-এ ভাগ করে: safe | approval | blocked।"""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return "safe", [f"syntax error — runtime-এ ধরা পড়বে: {e}"]

    reasons: list[str] = []
    level = "safe"

    def escalate(new_level: str, why: str):
        nonlocal level
        reasons.append(why)
        rank = {"safe": 0, "approval": 1, "blocked": 2}
        if rank[new_level] > rank[level]:
            level = new_level

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                root = a.name.split(".")[0]
                if a.name in BLOCKED_IMPORTS or root in BLOCKED_IMPORTS:
                    escalate("blocked", f"নিষিদ্ধ import: {a.name}")
                elif a.name in APPROVAL_IMPORTS or root in APPROVAL_IMPORTS:
                    escalate("approval", f"অনুমতি লাগবে এমন import: {a.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if node.module in BLOCKED_IMPORTS or root in BLOCKED_IMPORTS:
                escalate("blocked", f"নিষিদ্ধ import: {node.module}")
            elif node.module in APPROVAL_IMPORTS or root in APPROVAL_IMPORTS:
                escalate("approval", f"অনুমতি লাগবে এমন import: {node.module}")
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            short = name.split(".")[-1]
            if name in BLOCKED_CALLS or short in BLOCKED_CALLS:
                escalate("blocked", f"নিষিদ্ধ call: {name}")
            elif name in APPROVAL_CALLS or short in {"unlink", "rmtree"}:
                escalate("approval", f"অনুমতি লাগবে এমন call: {name}")
            elif short == "open":
                # লেখার mode-এ খোলা: নতুন file = safe; পুরনো file overwrite = approval;
                # work folder-এর বাইরে absolute পথ = approval।
                mode = ""
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    mode = str(node.args[1].value)
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = str(kw.value.value)
                if any(c in mode for c in "wax"):
                    path_lit = None
                    if node.args and isinstance(node.args[0], ast.Constant):
                        path_lit = str(node.args[0].value)
                    if path_lit and os.path.isabs(path_lit):
                        real = os.path.realpath(path_lit)
                        if not real.startswith(os.path.realpath(WORK_DIR)):
                            escalate("approval", f"work folder-এর বাইরে লেখা: {path_lit}")
                    elif path_lit and os.path.exists(os.path.join(WORK_DIR, path_lit)):
                        escalate("approval", f"পুরনো file overwrite: {path_lit}")
    return level, reasons


def ask_human(action: str, reasons: list[str]) -> bool:
    """APPROVAL_MODE অনুযায়ী মানুষের সিদ্ধান্ত।"""
    if APPROVAL_MODE == "grant":
        print(f"  🛂 Gate: অনুমতি আগেই দেওয়া আছে (grant) — {action}")
        return True
    if APPROVAL_MODE == "ask":
        ans = input(f"  🛂 Gate: '{action}' — কারণ: {'; '.join(reasons)}। অনুমতি দেবে? (y/n) ")
        return ans.strip().lower().startswith("y")
    print(f"  🛂 Gate: অনুমতি নেই (deny) — থামানো হলো: {action}")
    return False


# ---------------- Tools ----------------

def fetch_web_page(url: str) -> str:
    """Fetch a web page and return its readable text (first 4000 characters).

    Args:
        url: The full URL to fetch, e.g. https://news.ycombinator.com
    Returns:
        JSON string with status and the page text.
    """
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        lines = [ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip()]
        return json.dumps({"status": "ok", "url": url, "text": "\n".join(lines)[:4000]},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"},
                          ensure_ascii=False)


def run_python_code(code: str) -> str:
    """Run a Python code snippet safely in the work folder and return its output.

    The code passes a permission gate first: harmless code runs at once;
    destructive actions (deleting files, overwriting, network access) need
    human approval; dangerous escapes (subprocess, sockets, eval) never run.
    The code runs as a separate process with a 30-second limit, inside the
    work folder, with a minimal environment (no API keys).

    Args:
        code: Python source code to execute.
    Returns:
        JSON string with status, stdout and stderr — or the gate's decision.
    """
    level, reasons = classify_code(code)
    print(f"  🛂 Gate verdict: {level}" + (f" — {'; '.join(reasons)}" if reasons else ""))
    if level == "blocked":
        return json.dumps({"status": "blocked",
                           "error": "এই code নিরাপত্তা নিয়মে নিষিদ্ধ, চালানো হয়নি",
                           "reasons": reasons}, ensure_ascii=False)
    if level == "approval" and not ask_human("code চালানো", reasons):
        return json.dumps({"status": "needs_approval",
                           "error": "মানুষের অনুমতি ছাড়া এই ধাপ চালানো হয়নি — "
                                    "report-এ উল্লেখ করে বাকি কাজ শেষ করো",
                           "reasons": reasons}, ensure_ascii=False)
    try:
        env = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8",
               "PYTHONIOENCODING": "utf-8"}
        p = subprocess.run([sys.executable, "-c", code], cwd=WORK_DIR, env=env,
                           capture_output=True, text=True, timeout=30)
        return json.dumps({"status": "ok" if p.returncode == 0 else "error",
                           "stdout": p.stdout[:3000], "stderr": p.stderr[-1500:]},
                          ensure_ascii=False)
    except subprocess.TimeoutExpired:
        return json.dumps({"status": "error", "error": "code timed out after 30s"},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"},
                          ensure_ascii=False)


def _confined(filename: str) -> str | None:
    path = os.path.realpath(os.path.join(WORK_DIR, filename))
    return path if path.startswith(os.path.realpath(WORK_DIR)) else None


def read_text_file(filename: str) -> str:
    """Read a text file from the work folder to verify its contents.

    Args:
        filename: Name of the file inside the work folder, e.g. notes.txt
    Returns:
        JSON string with status and the file content.
    """
    path = _confined(filename)
    if path is None:
        return json.dumps({"status": "error", "error": "file must be inside work folder"},
                          ensure_ascii=False)
    try:
        with open(path, encoding="utf-8") as f:
            return json.dumps({"status": "ok", "filename": filename,
                               "content": f.read()[:4000]}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"},
                          ensure_ascii=False)


def write_text_file(filename: str, content: str) -> str:
    """Write a text file into the work folder.

    Overwriting an existing file needs human approval (permission gate);
    creating a new file runs at once. Paths outside the work folder are refused.

    Args:
        filename: Name of the file inside the work folder, e.g. notes.txt
        content: The full text content to write.
    Returns:
        JSON string with status — or the gate's decision.
    """
    path = _confined(filename)
    if path is None:
        return json.dumps({"status": "blocked",
                           "error": "work folder-এর বাইরে লেখা যায় না"}, ensure_ascii=False)
    if os.path.exists(path):
        if not ask_human(f"'{filename}' overwrite করা", ["পুরনো file-এর ওপর লেখা"]):
            return json.dumps({"status": "needs_approval",
                               "error": "মানুষের অনুমতি ছাড়া overwrite করা হয়নি"},
                              ensure_ascii=False)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return json.dumps({"status": "ok", "filename": filename,
                           "bytes": len(content.encode("utf-8"))}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"},
                          ensure_ascii=False)


# ---------------- Browser tools (Stage 3 — Playwright) ----------------
# একটি মাত্র browser পুরো mission জুড়ে থাকে (lazy start)। কোনো login/profile নেই।

_BROWSER: dict = {}
_BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def _page():
    if "page" not in _BROWSER:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        proxy = None
        relay = os.environ.get("AGENT_BROWSER_PROXY")
        if relay:
            proxy = {"server": relay}
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(
            user_agent=_BROWSER_UA, locale="en-US", proxy=proxy,
            ignore_https_errors=True,  # sandbox MITM CA; public pages only, no login
            viewport={"width": 1280, "height": 800})
        _BROWSER.update(pw=pw, browser=browser, page=ctx.new_page())
    return _BROWSER["page"]


def youtube_search(keyword: str, max_results: int = 5) -> str:
    """Search YouTube in a real browser and return structured results.

    Args:
        keyword: The search phrase, e.g. 'kids moral stories'
        max_results: How many top videos to return (default 5).
    Returns:
        JSON string: a list of {title, channel, views, age} from the live
        search results page — or an error/wall notice.
    """
    try:
        page = _page()
        url = "https://www.youtube.com/results?search_query=" + keyword.replace(" ", "+")
        page.goto(url, timeout=60000)
        try:
            page.wait_for_selector("ytd-video-renderer", timeout=30000)
        except Exception:
            text = page.inner_text("body")[:2000].lower()
            wall = [w for w in ("sign in to confirm", "unusual traffic",
                                "before you continue", "not a bot")
                    if w in text]
            return json.dumps({"status": "error",
                               "error": f"ফলাফল আসেনি; সম্ভাব্য দেয়াল: {wall or 'unknown'}"},
                              ensure_ascii=False)
        videos = page.evaluate("""(n) => {
          const out = [];
          for (const v of document.querySelectorAll('ytd-video-renderer')) {
            const t = v.querySelector('#video-title');
            if (!t) continue;
            const meta = [...v.querySelectorAll('#metadata-line span')].map(s => s.innerText);
            const ch = v.querySelector('ytd-channel-name #text');
            out.push({title: t.innerText.trim(),
                      channel: ch ? ch.innerText.trim() : '',
                      views: meta[0] || '', age: meta[1] || ''});
            if (out.length >= n) break;
          }
          return out;
        }""", max(1, min(int(max_results), 10)))
        return json.dumps({"status": "ok", "keyword": keyword, "results": videos},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"},
                          ensure_ascii=False)


def browser_open(url: str) -> str:
    """Open a public web page in the browser and return its title and text.

    Args:
        url: Full http(s) URL of a public page (no login pages).
    Returns:
        JSON string with the page title and a text excerpt.
    """
    if not url.startswith(("https://", "http://")):
        return json.dumps({"status": "blocked", "error": "শুধু http(s) URL চলবে"},
                          ensure_ascii=False)
    try:
        page = _page()
        page.goto(url, timeout=60000)
        page.wait_for_timeout(1500)
        return json.dumps({"status": "ok", "url": page.url, "title": page.title(),
                           "text": page.inner_text("body")[:3500]},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"},
                          ensure_ascii=False)


def browser_screenshot(filename: str) -> str:
    """Save a screenshot of the current browser page into the work folder.

    Args:
        filename: PNG file name inside the work folder, e.g. proof.png
    Returns:
        JSON string with status.
    """
    path = _confined(filename)
    if path is None:
        return json.dumps({"status": "blocked", "error": "work folder-এর বাইরে রাখা যায় না"},
                          ensure_ascii=False)
    try:
        _page().screenshot(path=path)
        return json.dumps({"status": "ok", "filename": filename}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"},
                          ensure_ascii=False)


TOOLS = [fetch_web_page, run_python_code, read_text_file, write_text_file,
         youtube_search, browser_open, browser_screenshot]
SCHEMAS = {fetch_web_page: FetchArgs, run_python_code: RunCodeArgs,
           read_text_file: ReadArgs, write_text_file: WriteArgs,
           youtube_search: YoutubeSearchArgs, browser_open: BrowserOpenArgs,
           browser_screenshot: ScreenshotArgs}
TOOL_MAP = {fn.__name__: fn for fn in TOOLS}

SYSTEM = (
    "You are an autonomous agent. You complete tasks by reasoning step by step and "
    "using your tools: fetch_web_page (read web pages), youtube_search (search YouTube "
    "in a real browser — structured results), browser_open (open a public page in the "
    "browser), browser_screenshot (save visual proof of the current page), "
    "run_python_code (process data, create files — safety-gated), read_text_file "
    "(verify files), write_text_file (write files — overwriting needs approval). "
    "Plan before acting. If a tool returns an error or an unexpected result, look at "
    "it, adjust, and continue — do not give up after one failure. If a tool returns "
    "status 'needs_approval' or 'blocked', do NOT try to bypass it in another way; "
    "note it clearly in your report and finish the rest. The browser never logs in "
    "anywhere. Always verify files you create by reading them back. "
    "Give your final report in Bengali (Bangla)."
)

MISSION = (
    "তুমি আমার YouTube channel-network-এর research agent। আজকের কাজ (Stage 3 proof — "
    "browser দিয়ে আসল niche research):\n"
    "1. youtube_search দিয়ে এই 3টি keyword-এর প্রতিটিতে top 5 video নাও: "
    "'kids moral stories', 'prophet muhammad stories for kids', 'islamic history stories'।\n"
    "2. run_python_code দিয়ে একটি script লিখে চালাও, যেটা সব ফলাফল দিয়ে "
    "'niche_research.csv' বানাবে। কলাম: keyword, title, channel, views, views_number, age। "
    "views_number = views লেখাটাকে সংখ্যায় বদলানো (যেমন '2M' → 2000000, '660K' → 660000)। "
    "শেষে মোট row সংখ্যা print করো।\n"
    "3. read_text_file দিয়ে niche_research.csv পড়ে যাচাই করো।\n"
    "4. browser_open দিয়ে তৃতীয় keyword-এর YouTube search page-টা খোলো "
    "(https://www.youtube.com/results?search_query=islamic+history+stories), "
    "তারপর browser_screenshot দিয়ে 'niche_proof.png' নামে ছবি রাখো (চোখের প্রমাণ)।\n"
    "5. write_text_file দিয়ে 'niche_report.txt' বানাও: কোন niche-এর top video-র views "
    "সবচেয়ে বেশি, কোন channel বারবার এসেছে, আর আমার 3টি channel-এর (SmartToon Fables, "
    "Seerat, Sonali Otiter Golpo) জন্য এক লাইন করে পর্যবেক্ষণ।\n"
    "6. বাংলায় final report দাও — কী কী পেলে, কোন niche সবচেয়ে শক্তিশালী মনে হলো।"
)


# ---------------- ReAct loop (আমাদের নিজের — AFC বন্ধ) ----------------

def run_mission(model: str) -> str:
    client = genai.Client(
        api_key=os.environ.get("GEMINI_API_KEY"),
        http_options=types.HttpOptions(api_version="v1beta", timeout=60_000),
    )
    config = types.GenerateContentConfig(
        tools=TOOLS, system_instruction=SYSTEM, temperature=0.4,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    contents = [types.Content(role="user", parts=[types.Part(text=MISSION)])]

    for step in range(1, MAX_STEPS + 1):
        resp = client.models.generate_content(model=model, contents=contents, config=config)
        content = resp.candidates[0].content
        contents.append(content)

        calls = [p for p in content.parts if getattr(p, "function_call", None)]
        texts = [p.text for p in content.parts if getattr(p, "text", None)]
        if texts:
            print(f"  🧠 {' '.join(texts)[:220]}")

        if not calls:
            return texts[0] if texts else "(কোনো উত্তর নেই)"

        responses = []
        for p in calls:
            fc = p.function_call
            args = dict(fc.args or {})
            brief = json.dumps(args, ensure_ascii=False)[:160]
            print(f"  🔧 Step {step}: {fc.name}({brief})")
            fn = TOOL_MAP.get(fc.name)
            if fn is None:
                result = json.dumps({"status": "error", "error": f"unknown tool {fc.name}"},
                                    ensure_ascii=False)
            else:
                try:
                    clean = SCHEMAS[fn].model_validate(args).model_dump()
                    result = fn(**clean)
                except ValidationError as e:
                    result = json.dumps({"status": "error",
                                         "error": f"schema যাচাই ব্যর্থ: {e.errors()[:2]}"},
                                        ensure_ascii=False)
                except Exception as e:
                    result = json.dumps({"status": "error",
                                         "error": f"{type(e).__name__}: {e}"},
                                        ensure_ascii=False)
            print(f"  👁  -> {result[:180]}")
            responses.append(types.Part.from_function_response(
                name=fc.name, response={"result": result}))
        contents.append(types.Content(role="user", parts=responses))

    return "(সর্বোচ্চ ধাপ শেষ — কাজ অসম্পূর্ণ)"


def main():
    print(f"[Stage 3 agent v4 — approval mode: {APPROVAL_MODE}]")
    for model in MODELS:
        print(f"\n=== Brain: {model} ===")
        try:
            report = run_mission(model)
        except Exception as e:
            print(f"⚠️ {model} দিয়ে mission শুরুই হয়নি ({type(e).__name__}) — fallback...")
            continue
        print("\n================ FINAL REPORT ================")
        print(report)
        return
    print("❌ কোনো model দিয়েই mission চলেনি")


if __name__ == "__main__":
    main()

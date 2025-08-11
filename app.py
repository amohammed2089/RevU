import os
import re
import json
import subprocess
import sys
import tempfile
import time
import random
from typing import List, Dict, Tuple, Optional

import streamlit as st
from openai import OpenAI, RateLimitError, APIError
from PIL import Image


# ===================== Page setup & styles =====================
st.set_page_config(page_title="RevU — Your AI Code Reviewer", page_icon="🤖", layout="wide")

CUSTOM_CSS = """
<style>
h1, h2, h3 { letter-spacing: 0.2px; }
.small-muted { color:#6b6f76; font-size:0.95rem; }
pre, code, textarea, .stTextArea textarea { border-radius: 10px !important; }
div[data-testid="stFileUploader"] section[aria-label="base"] { border-radius: 10px !important; }
.stButton > button {
  background: #e74c3c !important; color: white !important;
  border: 0 !important; border-radius: 8px !important;
  font-weight: 600 !important; padding: 0.75rem 1.1rem !important;
}
.stButton > button:hover { filter: brightness(0.95); }
.kv { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.92rem; }
.badge { display:inline-block; padding:2px 6px; border-radius:6px; background:#eef2ff; color:#1f2937; margin-left:6px; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ===================== Sidebar =====================
with st.sidebar:
    st.header("Settings")
    language = st.selectbox("Language", ["Auto", "Python", "JavaScript / Other"], index=0)
    run_runtime = st.toggle("Run runtime checks (sandboxed subprocess)", value=False,
                            help="Executes code in an isolated Python subprocess with -I, -X dev, and warnings enabled. "
                                 "May still run user code — enable only when you trust the snippet.")
    show_warnings = st.toggle("Report warnings (Deprecation/Resource/Encoding/etc.)", value=True)
    use_ai = st.toggle("AI suggestions (requires OPENAI_API_KEY)", value=False)
    st.markdown(
        "<p class='small-muted'>Tip: Python uses compile check ➜ optional runtime probe ➜ Ruff ➜ static security scan ➜ (optional) AI.</p>",
        unsafe_allow_html=True
    )


# ===================== Title + subheader =====================
st.markdown("## RevU — Your AI Code Reviewer")
st.markdown(
    "<p class='small-muted'>Paste code or upload a file. RevU catches compile errors, runtime exceptions, warnings, security smells, and Ruff issues.</p>",
    unsafe_allow_html=True
)

# ===================== Two-column layout =====================
col_img, col_ui = st.columns([0.9, 1.3], vertical_alignment="top")

with col_img:
    try:
        if os.path.exists("robot.png"):
            st.image(Image.open("robot.png"), use_column_width=True)
        else:
            st.markdown("🧑‍💻")
    except Exception:
        st.markdown("🧑‍💻")

with col_ui:
    label = "Paste your code here – sit back and let RevU catch every code flaw"
    code = st.text_area(label, height=260, placeholder="# Paste code or upload a file below…")

    uploaded = st.file_uploader("…or upload a code file", type=None)
    filename = None
    if uploaded and not code:
        try:
            code = uploaded.read().decode("utf-8", errors="ignore")
            filename = uploaded.name
        except Exception:
            code = ""

    run_clicked = st.button("🔎 Review Code", use_container_width=True)


# ===================== Helpers =====================
PY_EXE = sys.executable or "python"


def detect_language(src: str, name: Optional[str]) -> str:
    if language != "Auto":
        return language
    if name and name.endswith(".py"):
        return "Python"
    py_tokens = ("import ", "def ", "class ", "from ", "print(")
    if any(tok in src for tok in py_tokens):
        return "Python"
    return "JavaScript / Other"


def table_from_records(records: List[Dict], title: str):
    if not records:
        st.success(f"✅ No {title.lower()} found.")
        return
    st.subheader(title)
    st.table(records)


# ===================== Compile check (Python) =====================
def compile_check(src: str) -> List[Dict]:
    try:
        compile(src, "<user_code>", "exec")
        return []
    except Exception as e:
        return [{
            "Rule": type(e).__name__,
            "Message": str(e),
            "Line": getattr(e, "lineno", None),
            "Column": getattr(e, "offset", None),
            "File": "<user_code>",
        }]


# ===================== Runtime probe (Python) =====================
TRACE_RE = re.compile(
    r'^\s*File "(?P<file>.+?)", line (?P<line>\d+),.*?\n(?P<code>.+?)\n(?P<etype>[A-Za-z_][A-Za-z0-9_\.]*): (?P<emsg>.*)$',
    re.S | re.M
)

WARN_RE = re.compile(
    r'^(?P<file>.+?):(?P<line>\d+): (?P<category>\w+Warning): (?P<message>.+)$',
    re.M
)


def run_runtime_probe(src: str, capture_warnings: bool = True, timeout: float = 3.0) -> Tuple[str, str, int]:
    """Run code in an isolated child Python with warnings enabled; returns (stdout, stderr, rc)."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8") as f:
        f.write(src)
        path = f.name
    try:
        cmd = [PY_EXE, "-I", "-X", "dev"]
        if capture_warnings:
            cmd += ["-W", "default"]
        cmd += [path]
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env={})
        return completed.stdout, completed.stderr, completed.returncode
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def parse_first_exception(stderr: str) -> Optional[Dict]:
    # Last "ExceptionType: message" usually wins; use regex from final traceback block.
    # Fallback: simple last-line parse.
    matches = list(TRACE_RE.finditer(stderr))
    if matches:
        m = matches[-1]
        etype = m.group("etype").strip()
        emsg = m.group("emsg").strip()
        file_ = m.group("file")
        line = int(m.group("line"))
        return {"Rule": etype, "Message": emsg, "Line": line, "File": file_}
    # Fallback to last line
    lines = [ln for ln in stderr.strip().splitlines() if ln.strip()]
    if lines:
        last = lines[-1]
        if ":" in last:
            etype, emsg = last.split(":", 1)
            return {"Rule": etype.strip(), "Message": emsg.strip(), "Line": None, "File": "<user_code>"}
    return None


def parse_warnings(stderr: str) -> List[Dict]:
    res = []
    for m in WARN_RE.finditer(stderr):
        res.append({
            "Category": m.group("category"),
            "Message": m.group("message"),
            "Line": int(m.group("line")),
            "File": m.group("file"),
        })
    return res


# ===================== Static Security & Error-handling scan =====================
SECURITY_PATTERNS = [
    (r'\beval\s*\(', "Use of eval()", "High"),
    (r'\bexec\s*\(', "Use of exec()", "High"),
    (r'\bpickle\.loads\s*\(', "Untrusted pickle deserialization", "High"),
    (r'\byaml\.load\s*\(', "yaml.load without SafeLoader", "High"),
    (r'\bsubprocess\.[A-Za-z_]+\s*\(.*shell\s*=\s*True', "subprocess with shell=True", "High"),
    (r'["\']?(password|secret|token|apikey|api_key)["\']?\s*[:=]\s*["\'][^"\']+["\']', "Possible hardcoded secret", "High"),
    (r'\brequests\.(get|post|put|delete|patch)\s*\(', "HTTP call without timeout", "Medium"),
]

ERROR_HANDLING_PATTERNS = [
    (r'\bexcept\s*:\s*', "Bare except clause", "High"),
    (r'\bexcept\s+BaseException\b', "Catching BaseException", "High"),
    (r'\bexcept\s+Exception\s*:\s*pass\b', "Swallowing Exception without handling", "Medium"),
]

ASYNC_SMELLS = [
    (r'\basync\s+def\b', "Async function present (review awaits, blocking calls, and cancellation handling)", "Info"),
    (r'\bawait\b', "Await usage detected (check for proper async patterns)", "Info"),
]


def run_static_scans(src: str) -> List[Dict]:
    findings = []
    def add(rule, msg, sev, line):
        findings.append({"Rule": rule, "Message": msg, "Severity": sev, "Line": line})

    for pat, msg, sev in SECURITY_PATTERNS:
        for m in re.finditer(pat, src):
            line = src.count("\n", 0, m.start()) + 1
            add("Security", msg, sev, line)

    for pat, msg, sev in ERROR_HANDLING_PATTERNS:
        for m in re.finditer(pat, src):
            line = src.count("\n", 0, m.start()) + 1
            add("ErrorHandling", msg, sev, line)

    for pat, msg, sev in ASYNC_SMELLS:
        for m in re.finditer(pat, src):
            line = src.count("\n", 0, m.start()) + 1
            add("Async", msg, sev, line)

    # Mutable default args (common pitfall)
    for m in re.finditer(r'def\s+\w+\s*\([^)]*(\w+\s*=\s*\[\]|\w+\s*=\s*\{\})[^)]*\)', src):
        line = src.count("\n", 0, m.start()) + 1
        add("Maintainability", "Mutable default argument", "Medium", line)

    # Broad except without logging or re-raise (heuristic)
    for m in re.finditer(r'except\s+Exception\s*:\s*(?:pass|return\s+None\b)', src):
        line = src.count("\n", 0, m.start()) + 1
        add("ErrorHandling", "Broad except without handling", "Medium", line)

    return findings


# ===================== Ruff (Python) =====================
def run_ruff_on_code(src: str) -> List[Dict]:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8") as f:
        f.write(src)
        tmp_path = f.name
    try:
        completed = subprocess.run(
            ["ruff", "check", "--output-format=json", tmp_path],
            capture_output=True, text=True
        )
        output = completed.stdout.strip()
        if not output:
            return []
        return json.loads(output)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def show_ruff_results(results: List[Dict]):
    if not results:
        st.success("✅ No Ruff issues found.")
        return

    st.subheader("Ruff findings (Python)")
    counts = {}
    for r in results:
        code = r.get("code")
        if code:
            counts[code] = counts.get(code, 0) + 1
    if counts:
        st.caption("Counts by rule:")
        st.write({k: v for k, v in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)})

    rows = []
    for r in results:
        loc = r.get("location", {})
        rows.append({
            "Rule": r.get("code"),
            "Message": r.get("message"),
            "Line": loc.get("row"),
            "Column": loc.get("column"),
            "File": r.get("filename")
        })
    st.table(rows)


# ===================== AI review (explicit taxonomy + backoff) =====================
AI_CHECKLIST = r"""
You are a senior code reviewer. Give precise, actionable feedback with short code snippets.
Catch EVERYTHING from tiny style issues to critical failures. Use these headings and mark each finding with [Critical]/[High]/[Medium]/[Low].
Group findings, be concise, and propose concrete fixes (diff-style or small code blocks).

=== CORE CATEGORIES ===
[Severity] Syntax & parsing (SyntaxError, IndentationError, TabError)
[Severity] Runtime errors & exceptions (full Python hierarchy)
[Severity] Logic & algorithmic correctness
[Severity] Security (injections, traversal, secrets, unsafe deserialization, authN/authZ, SSRF, RCE)
[Severity] Performance & complexity (hot loops, N+1, large allocations)
[Severity] Concurrency/async pitfalls (deadlocks, races, blocking in async, cancellations)
[Severity] Resource handling (files/sockets/processes, leaks, context managers)
[Severity] Input validation & edge cases (bounds, None/Null, types, user input)
[Severity] Error handling & resilience (correct exception types, retries/backoff, fallbacks)
[Severity] API usage & compatibility (deprecated, wrong params, unsafe defaults)
[Severity] Maintainability & readability (naming, comments, duplication, long functions)
[Severity] Style/formatting (PEP8/ruff rules, consistent imports)
[Severity] Testing & coverage (missing unit tests, fuzz/edge tests)
[Severity] Dependencies & config risks (vulnerable/outdated libs, hardcoded creds)
[Severity] Web-specific headers/CORS/auth when relevant

=== EXCEPTIONS TO RECOGNIZE ===
BaseException: SystemExit, KeyboardInterrupt, GeneratorExit, asyncio.CancelledError
Exception family (sample): ArithmeticError→(ZeroDivisionError, OverflowError, FloatingPointError), AssertionError, AttributeError,
BufferError, EOFError, ImportError→ModuleNotFoundError, LookupError→(IndexError, KeyError), MemoryError, NameError→UnboundLocalError,
OSError tree (BlockingIOError, ChildProcessError, ConnectionError→BrokenPipe/Aborted/Refused/Reset, FileExists/FileNotFound,
InterruptedError, IsADirectoryError, NotADirectoryError, PermissionError, ProcessLookupError, TimeoutError),
ReferenceError, RuntimeError→(NotImplementedError, RecursionError), StopIteration, StopAsyncIteration,
SyntaxError→(IndentationError, TabError), SystemError, TypeError, ValueError→UnicodeError→(UnicodeDecode/Encode/Translate)

Warnings: UserWarning, DeprecationWarning, PendingDeprecationWarning, FutureWarning, SyntaxWarning, RuntimeWarning,
ImportWarning, UnicodeWarning, BytesWarning, ResourceWarning, EncodingWarning.

=== HANDLING GUIDELINES ===
- Flag unhandled exceptions; suggest specific try/except with correct types (avoid blanket catch; never swallow BaseException).
- For warnings, propose fixes or filters.
- Show safer patterns (context managers, timeouts on I/O, async best-practices).
- Provide boundary tests.
- For security, propose minimal safe fix and point to risky API/pattern.
"""

def _ai_review_once(client: OpenAI, prompt_code: str, language_hint: str) -> str:
    user_msg = f"Language: {language_hint}\n\nCode to review:\n\n{prompt_code}"
    resp = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {"role": "system", "content": AI_CHECKLIST},
            {"role": "user", "content": user_msg},
        ],
    )
    return resp.output_text.strip()


@st.cache_data(ttl=120)
def cached_ai_review(prompt_code: str, language_hint: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY", None)
    if not api_key:
        return "No OPENAI_API_KEY found. Add it via App ▸ Settings ▸ Advanced ▸ Secrets."
    os.environ["OPENAI_API_KEY"] = api_key
    client = OpenAI()

    last_err = None
    for attempt in range(6):
        try:
            return _ai_review_once(client, prompt_code, language_hint)
        except RateLimitError as e:
            last_err = e
            time.sleep((2 ** attempt) + random.random())
            continue
        except APIError as e:
            last_err = e
            time.sleep(2)
            continue
        except Exception as e:
            return f"AI review error: {e}"
    return "AI is busy (rate limited). Please try again shortly."


# ===================== Run review =====================
if run_clicked:
    if not code or not code.strip():
        st.warning("Please paste code or upload a file first.")
        st.stop()

    lang = detect_language(code, filename)

    if lang != "Python":
        st.info("Non-Python detected. Static checks are limited; enable AI suggestions for deeper review.")
    else:
        # 1) Compile-time errors
        st.info("Running compile check…")
        comp = compile_check(code)
        table_from_records(comp, "Compile-time Errors")
        has_compiler_blockers = any(r["Rule"] in ("SyntaxError", "IndentationError", "TabError") for r in comp)

        # 2) Runtime probe (optional)
        if run_runtime and not has_compiler_blockers:
            st.info("Running sandboxed runtime probe…")
            try:
                out, err, rc = run_runtime_probe(code, capture_warnings=show_warnings, timeout=3.5)
                first_exc = parse_first_exception(err)
                if first_exc:
                    table_from_records([first_exc], "Runtime Exception (first raised)")
                else:
                    st.success("✅ No exception raised in short probe.")
                if show_warnings:
                    warns = parse_warnings(err)
                    table_from_records(warns, "Warnings")
                if out.strip():
                    with st.expander("Program stdout"):
                        st.code(out)
                if err.strip():
                    with st.expander("Program stderr / traceback"):
                        st.code(err)
            except subprocess.TimeoutExpired:
                st.warning("Runtime probe timed out (code may block or run too long).")
            except Exception as e:
                st.error(f"Runtime probe error: {e}")

        # 3) Ruff (lint)
        st.info("Running Ruff (Python linter)…")
        try:
            ruff_results = run_ruff_on_code(code)
            show_ruff_results(ruff_results)
        except FileNotFoundError:
            st.error("Ruff not installed. Ensure `ruff==0.6.9` is in requirements.txt.")
        except Exception as e:
            st.error(f"Ruff error: {e}")

        # 4) Static security & error-handling scan
        st.info("Scanning for security & error-handling smells…")
        sec = run_static_scans(code)
        if sec:
            st.subheader("Security & Error-handling Findings")
            st.table(sec)
        else:
            st.success("✅ No security/error-handling smells detected by heuristics.")

    # 5) AI suggestions (optional)
    if use_ai:
        with st.spinner("Generating AI suggestions…"):
            feedback = cached_ai_review(code, lang)
        st.subheader("💡 AI Suggestions")
        st.write(feedback)
    else:
        st.caption("Toggle AI suggestions in the sidebar for a deeper review.")


# ===================== Footer =====================
st.markdown("<hr/>", unsafe_allow_html=True)
st.caption("RevU • Catch syntax, runtime, warnings, security, Ruff issues • Made with ❤️")

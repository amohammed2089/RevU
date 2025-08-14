import os
import json
import subprocess
import tempfile
import time
import random
from typing import List, Dict

import streamlit as st
from openai import OpenAI, RateLimitError, APIError
from PIL import Image


# -------------------- Page setup & styles --------------------
st.set_page_config(page_title="RevU — Your AI Code Reviewer", page_icon="🤖", layout="wide")

CUSTOM_CSS = """
<style>
h1, h2, h3 { letter-spacing: 0.2px; }
.small-muted { color:#6b6f76; font-size:0.95rem; }

.stButton > button {
  background: #e74c3c !important;
  color: white !important;
  border: 0 !important;
  border-radius: 8px !important;
  font-weight: 600 !important;
  padding: 0.75rem 1.1rem !important;
}
.stButton > button:hover { filter: brightness(0.95); }

textarea, .stTextArea textarea { border-radius: 10px !important; }
div[data-testid="stFileUploader"] section[aria-label="base"] { border-radius: 10px !important; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# -------------------- Sidebar --------------------
with st.sidebar:
    st.header("Settings")
    language = st.selectbox("Language", ["Auto", "Python", "JavaScript / Other"], index=0)
    use_ai = st.toggle("AI suggestions (requires OPENAI_API_KEY)", value=False)
    debug = st.checkbox("Show debug", value=False)
    st.markdown(
        "<p class='small-muted'>Tip: For Python, Ruff runs locally. For other languages, AI suggestions still help.</p>",
        unsafe_allow_html=True
    )


# -------------------- Title + subheader --------------------
st.markdown("### ")
st.markdown("## RevU — Your AI Code Reviewer: From tiny typos to fatal flaws, nothing escapes.")
st.markdown(
    "<p class='small-muted'>Paste code or upload a file. Get instant lint feedback (Python via Ruff) and optional AI suggestions.</p>",
    unsafe_allow_html=True
)


# -------------------- Two-column layout --------------------
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
    label = "Paste your code here –  Sit back, relax, and let RevU catch every code flaw"
    code = st.text_area(label, height=240, placeholder="# Paste code or upload a file below…")

    uploaded = st.file_uploader("…or upload a code file", type=None)
    if uploaded and not code:
        try:
            code = uploaded.read().decode("utf-8", errors="ignore")
        except Exception:
            code = ""

    run_clicked = st.button("🔎 Review Code", use_container_width=True)


# -------------------- Ruff helpers --------------------
def run_ruff_on_code(src: str) -> List[Dict]:
    """Write code to a temp .py and run ruff with JSON output."""
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


# -------------------- AI review (explicit taxonomy + backoff) --------------------
def _ai_review_once(client: OpenAI, prompt_code: str, language_hint: str) -> str:
    # Full-spectrum, explicit checklist including Python exception & warning families
    checklist = r"""
You are a senior code reviewer. Give precise, actionable feedback with short code snippets.
Your job is to catch EVERYTHING from tiny style issues to critical failures. Use these headings and mark each finding with [Critical]/[High]/[Medium]/[Low].
Group findings, be concise, and propose concrete fixes (diff-style or small code blocks).

=== CORE CATEGORIES ===
[Severity] Syntax & parsing (SyntaxError, IndentationError, TabError)
[Severity] Runtime errors & exceptions (see explicit lists below)
[Severity] Logic & algorithmic correctness
[Severity] Security (injections, path traversal, secrets, unsafe deserialization, authN/authZ, SSRF, RCE)
[Severity] Performance & complexity (hot loops, N+1, large allocations)
[Severity] Concurrency/async pitfalls (deadlocks, races, blocking calls in async)
[Severity] Resource handling (files/sockets/processes, leaks, context managers)
[Severity] Input validation & edge cases (bounds, None/Null, types, user input)
[Severity] Error handling & resilience (correct exception types, retries/backoff, fallbacks)
[Severity] API usage & compatibility (deprecated, wrong params, unsafe defaults)
[Severity] Maintainability & readability (naming, comments, duplication, long functions)
[Severity] Style/formatting (PEP8/ruff rules, consistent imports)
[Severity] Testing & coverage (missing unit tests, fuzz/edge tests)
[Severity] Dependencies & config risks (vulnerable/outdated libs, hardcoded creds, unsafe settings)
[Severity] Web-specific headers/CORS/auth when relevant

=== PYTHON EXCEPTIONS — EXPLICITLY CHECK THESE ===
# BaseException family (usually re-raise or let terminate)
- BaseException (generic termination signal)
- SystemExit
- KeyboardInterrupt
- GeneratorExit
- asyncio.CancelledError   # BaseException since 3.8; task cancellations

# Exception family (typical catchable errors)
- ArithmeticError → ZeroDivisionError, OverflowError, FloatingPointError
- AssertionError
- AttributeError
- BufferError
- EOFError
- ImportError → ModuleNotFoundError
- LookupError → IndexError, KeyError
- MemoryError
- NameError → UnboundLocalError
- OSError (see OS/I/O section below)
- ReferenceError
- RuntimeError → NotImplementedError, RecursionError
- StopIteration, StopAsyncIteration
- SyntaxError → IndentationError, TabError
- SystemError
- TypeError
- ValueError → UnicodeError → UnicodeDecodeError, UnicodeEncodeError, UnicodeTranslateError

# OS / I/O subclasses (OSError family; explicitly recognize)
- OSError (IOError alias in Py3)
- BlockingIOError, ChildProcessError
- ConnectionError → BrokenPipeError, ConnectionAbortedError, ConnectionRefusedError, ConnectionResetError
- FileExistsError, FileNotFoundError
- InterruptedError
- IsADirectoryError, NotADirectoryError
- PermissionError, ProcessLookupError
- TimeoutError

# Warning classes (capture/route correctly; use warnings module / filters as needed)
- Warning (base)
- UserWarning
- DeprecationWarning, PendingDeprecationWarning, FutureWarning
- SyntaxWarning, RuntimeWarning, ImportWarning
- UnicodeWarning, BytesWarning, ResourceWarning
- EncodingWarning (PEP 597; default encoding warnings)

# Async/concurrency special cases
- asyncio.CancelledError (prefer to re-raise on task cancellation)
- asyncio.InvalidStateError (task/future state issues)
- concurrent.futures.CancelledError (library-specific cancellation)

=== HANDLING GUIDELINES ===
- Flag unhandled exceptions; suggest specific try/except blocks with the **correct** exception types (avoid blanket `except Exception` unless justified; never swallow BaseException).
- For warnings, propose `warnings.warn`, category-specific filters, or code fixes to eliminate future deprecations.
- Show safer patterns (context managers for files/sockets, timeouts on network I/O, `async with`, `await` correctness).
- Provide input validation examples and boundary tests.
- When security is implicated, show minimal safe fix and reference the risky API or pattern.

Return a compact, well-structured review grouped by the headings above with practical fixes.
"""
    user_msg = f"Language: {language_hint}\n\nCode to review:\n\n{prompt_code}"

    resp = client.responses.create(
        model="gpt-4o-mini",  # lighter model helps avoid rate limits; upgrade if needed
        input=[
            {"role": "system", "content": checklist},
            {"role": "user", "content": user_msg},
        ],
    )
    return resp.output_text.strip()


@st.cache_data(ttl=120)
def cached_ai_review(prompt_code: str, language_hint: str) -> str:
    """Retry on rate limits/transient errors and cache briefly."""
    api_key = os.environ.get("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY", None)
    if not api_key:
        return "AI review error: OPENAI_API_KEY not found in Secrets."

    os.environ["OPENAI_API_KEY"] = api_key
    client = OpenAI()

    last_err = None
    for attempt in range(6):  # exponential backoff up to ~1 minute
        try:
            text = _ai_review_once(client, prompt_code, language_hint)
            if text and text.strip():
                return text.strip()
            last_err = "Empty AI response"
        except RateLimitError as e:
            last_err = f"RateLimitError: {e}"
        except APIError as e:
            last_err = f"APIError: {e}"
        except Exception as e:
            last_err = f"Exception: {e}"
        time.sleep((2 ** attempt) + random.random())

    return f"AI review error after retries: {last_err}"


# -------------------- Run review --------------------
if run_clicked:
    if not code or not code.strip():
        st.warning("Please paste code or upload a file first.")
        st.stop()

    # detect language (simple heuristic)
    lang = language
    if lang == "Auto":
        if uploaded and uploaded.name.endswith(".py"):
            lang = "Python"
        elif any(tok in code for tok in ["import ", "def ", "class "]):
            lang = "Python"
        else:
            lang = "JavaScript / Other"

    # Ruff for Python
    if lang == "Python":
        st.info("Running Ruff (Python linter) locally…")
        try:
            ruff_results = run_ruff_on_code(code)
            show_ruff_results(ruff_results)
        except FileNotFoundError:
            st.error("Ruff not installed. Ensure `ruff==0.6.9` is in requirements.txt.")
        except Exception as e:
            st.error(f"Ruff error: {e}")
    else:
        st.caption("Skipping Ruff (Python-only).")

    if use_ai:
        with st.spinner("Generating AI suggestions…"):
            feedback = cached_ai_review(code, lang)

        st.subheader("💡 AI Suggestions")
        if not feedback or not feedback.strip():
            st.error("No AI text returned. Check logs and secrets.")
        else:
            st.write(feedback)

        if debug:
            st.code(feedback if isinstance(feedback, str) else str(feedback), language="markdown")
    else:
        st.caption("Toggle AI suggestions in the sidebar to get deep review.")

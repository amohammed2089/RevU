import os
import json
import csv
import io
import subprocess
import tempfile
from typing import List, Dict

import streamlit as st
from PIL import Image

# -------------------- Page setup & styles --------------------
st.set_page_config(page_title="RevU — Your Code Reviewer (No AI)", page_icon="🤖", layout="wide")

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
    st.markdown(
        "<p class='small-muted'>Tip: For Python, Ruff runs locally. This app runs with <b>no AI</b>.</p>",
        unsafe_allow_html=True
    )

# -------------------- Title + subheader --------------------
st.markdown("### ")
st.markdown("## RevU — Your AI-Free Code Reviewer: From tiny typos to fatal flaws, nothing escapes.")
st.markdown(
    "<p class='small-muted'>Paste code or upload a file. Get instant <b>Python</b> lint feedback via Ruff and download a full Python error catalog.</p>",
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
    label = "Paste your code here –  Sit back, relax, and let RevU catch code issues"
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

# Map common message patterns to Python error types
ERROR_PATTERNS = [
    ("syntaxerror", "SyntaxError"),
    ("expected ':'", "SyntaxError"),
    ("expected an indented block", "IndentationError"),
    ("indentation", "IndentationError"),
    ("taberror", "TabError"),
    ("undefined name", "NameError"),
    ("name is not defined", "NameError"),
    ("unboundlocalerror", "UnboundLocalError"),
    ("attributeerror", "AttributeError"),
    ("has no attribute", "AttributeError"),
    ("typeerror", "TypeError"),
    ("unsupported operand type", "TypeError"),
    ("valuerror", "ValueError"),
    ("valueerror", "ValueError"),
    ("unicodeencodeerror", "UnicodeEncodeError"),
    ("unicodedecodeerror", "UnicodeDecodeError"),
    ("unicodetranslateerror", "UnicodeTranslateError"),
    ("zerodivisionerror", "ZeroDivisionError"),
    ("division by zero", "ZeroDivisionError"),
    ("indexerror", "IndexError"),
    ("list index out of range", "IndexError"),
    ("tuple index out of range", "IndexError"),
    ("keyerror", "KeyError"),
    ("module not found", "ModuleNotFoundError"),
    ("modulenotfounderror", "ModuleNotFoundError"),
    ("importerror", "ImportError"),
    ("filenotfounderror", "FileNotFoundError"),
    ("permissionerror", "PermissionError"),
    ("timeouterror", "TimeoutError"),
    ("connectionerror", "ConnectionError"),
    ("broken pipe", "BrokenPipeError"),
    ("runtimeerror", "RuntimeError"),
    ("recursionerror", "RecursionError"),
    ("notimplementederror", "NotImplementedError"),
    ("systemerror", "SystemError"),
    ("memoryerror", "MemoryError"),
    ("eoferror", "EOFError"),
]

def _guess_error_type(message: str, default_code: str | None) -> str:
    msg = (message or "").lower()
    for needle, tag in ERROR_PATTERNS:
        if needle in msg:
            return tag
    return default_code or "Lint/Style"

def classify_findings(results: List[Dict]) -> List[Dict]:
    """Map Ruff messages to a 'Type of Error' column when obvious."""
    table = []
    for r in results:
        loc = r.get("location", {})
        msg = r.get("message", "")
        etype = _guess_error_type(msg, r.get("code"))
        table.append({
            "Type of Error": etype,
            "Message": msg,
            "Line": loc.get("row"),
            "Column": loc.get("column"),
            "File": r.get("filename")
        })
    return table

def to_csv(rows: List[Dict], headers: List[str]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in headers})
    return buf.getvalue().encode("utf-8")

def show_ruff_results(results: List[Dict]):
    if not results:
        st.success("✅ No Ruff issues found.")
        return

    st.subheader("Ruff findings (Python)")
    rows = classify_findings(results)
    st.table(rows)

    # Download button for Ruff findings
    csv_bytes = to_csv(rows, ["Type of Error", "Message", "Line", "Column", "File"])
    st.download_button(
        label="⬇️ Download Ruff findings (CSV)",
        data=csv_bytes,
        file_name="ruff_findings.csv",
        mime="text/csv"
    )

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
        st.warning("This app’s local checks are Python-focused. Paste Python to see detailed findings.")

# -------------------- Comprehensive Error Catalog (Python) --------------------
st.markdown("## 🧭 Comprehensive Error Catalog (Python)")
st.caption("Built from official docs: built-in exceptions, warnings, asyncio exceptions, and OS/I/O subclasses. Download as CSV below.")

def build_error_catalog() -> List[Dict]:
    cat: List[Dict] = []

    def add(category: str, item: str, notes: str = ""):
        cat.append({"Category": category, "Item": item, "Notes": notes})

    # BaseException family
    base = "BaseException family"
    for item, notes in [
        ("BaseException", "Generic termination signal"),
        ("SystemExit", ""),
        ("KeyboardInterrupt", ""),
        ("GeneratorExit", ""),
        ("asyncio.CancelledError", "Subclass of BaseException since 3.8; task cancellation"),
    ]:
        add(base, item, notes)

    # Exception family
    exc = "Exception family"
    for item, notes in [
        ("ArithmeticError", "ZeroDivisionError, OverflowError, FloatingPointError"),
        ("ZeroDivisionError", ""),
        ("OverflowError", ""),
        ("FloatingPointError", ""),
        ("AssertionError", ""),
        ("AttributeError", ""),
        ("BufferError", ""),
        ("EOFError", ""),
        ("ImportError", "ModuleNotFoundError"),
        ("ModuleNotFoundError", ""),
        ("LookupError", "IndexError, KeyError"),
        ("IndexError", ""),
        ("KeyError", ""),
        ("MemoryError", ""),
        ("NameError", "UnboundLocalError"),
        ("UnboundLocalError", ""),
        ("OSError", "See OS/I-O section"),
        ("ReferenceError", ""),
        ("RuntimeError", "NotImplementedError, RecursionError"),
        ("NotImplementedError", ""),
        ("RecursionError", ""),
        ("StopIteration", ""),
        ("StopAsyncIteration", ""),
        ("SyntaxError", "IndentationError, TabError"),
        ("IndentationError", ""),
        ("TabError", ""),
        ("SystemError", ""),
        ("TypeError", ""),
        ("ValueError", "UnicodeError"),
        ("UnicodeError", "UnicodeDecodeError, UnicodeEncodeError, UnicodeTranslateError"),
        ("UnicodeDecodeError", ""),
        ("UnicodeEncodeError", ""),
        ("UnicodeTranslateError", ""),
    ]:
        add(exc, item, notes)

    # OS / I/O subclasses (OSError)
    osio = "OS / I-O (OSError)"
    for item in [
        "BlockingIOError",
        "ChildProcessError",
        "ConnectionError",
        "BrokenPipeError",
        "ConnectionAbortedError",
        "ConnectionRefusedError",
        "ConnectionResetError",
        "FileExistsError",
        "FileNotFoundError",
        "InterruptedError",
        "IsADirectoryError",
        "NotADirectoryError",
        "PermissionError",
        "ProcessLookupError",
        "TimeoutError",
    ]:
        add(osio, item)

    # Warning classes
    warn = "Warnings"
    for item in [
        "Warning",
        "UserWarning",
        "DeprecationWarning",
        "PendingDeprecationWarning",
        "FutureWarning",
        "SyntaxWarning",
        "RuntimeWarning",
        "ImportWarning",
        "UnicodeWarning",
        "BytesWarning",
        "ResourceWarning",
        "EncodingWarning",
    ]:
        add(warn, item)

    # Async / Concurrency specials
    async_cat = "Async / Concurrency"
    for item, notes in [
        ("asyncio.CancelledError", "Usually re-raise after cleanup"),
        ("asyncio.InvalidStateError", "Task/Future misuse"),
        ("concurrent.futures.CancelledError", "Cancellation in futures"),
    ]:
        add(async_cat, item, notes)

    return cat

catalog = build_error_catalog()

# Download button for the catalog
catalog_csv = to_csv(catalog, ["Category", "Item", "Notes"])
st.download_button(
    label="⬇️ Download Comprehensive Error Catalog (CSV)",
    data=catalog_csv,
    file_name="python_error_catalog.csv",
    mime="text/csv",
)

# Short references
st.caption(
    "Sources: Python built-in exceptions, warnings, asyncio exceptions, and Streamlit download button docs."
)
st.markdown(
    "- Built-in exceptions: https://docs.python.org/3/library/exceptions.html  \n"
    "- Warnings: https://docs.python.org/3/library/warnings.html  \n"
    "- asyncio exceptions: https://docs.python.org/3/library/asyncio-exceptions.html  \n"
    "- Task cancellation guidance: https://docs.python.org/3/library/asyncio-task.html  \n"
    "- Streamlit `st.download_button`: https://docs.streamlit.io/develop/api-reference/widgets/st.download_button"
)

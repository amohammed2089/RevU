import os
import json
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
        "<p class='small-muted'>Tip: For Python, Ruff runs locally. This app now runs with NO AI.</p>",
        unsafe_allow_html=True
    )

# -------------------- Title + subheader --------------------
st.markdown("### ")
st.markdown("## RevU — Your AI-Free Code Reviewer: From tiny typos to fatal flaws, nothing escapes.")
st.markdown(
    "<p class='small-muted'>Paste code or upload a file. Get instant <b>Python</b> lint feedback via Ruff and see a comprehensive Python error catalog below.</p>",
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

def classify_findings(results: List[Dict]) -> List[Dict]:
    """Map Ruff messages to a 'Type of Error' column when obvious (e.g., SyntaxError)."""
    table = []
    for r in results:
        loc = r.get("location", {})
        msg = r.get("message", "")
        etype = None
        # Simple mappings for clarity in the UI
        if "SyntaxError" in msg or "syntax" in msg.lower():
            etype = "SyntaxError"
        elif "Indentation" in msg:
            etype = "IndentationError"
        elif "Name is not defined" in msg or "undefined name" in msg.lower():
            etype = "NameError"
        elif "attribute" in msg.lower():
            etype = "AttributeError"
        elif "division by zero" in msg.lower():
            etype = "ZeroDivisionError"
        elif "index" in msg.lower() and "out of range" in msg.lower():
            etype = "IndexError"
        elif "permission" in msg.lower():
            etype = "PermissionError (runtime)"
        else:
            etype = r.get("code") or "Lint/Style"

        table.append({
            "Type of Error": etype,
            "Message": msg,
            "Line": loc.get("row"),
            "Column": loc.get("column"),
            "File": r.get("filename")
        })
    return table

def show_ruff_results(results: List[Dict]):
    if not results:
        st.success("✅ No Ruff issues found.")
        return

    st.subheader("Ruff findings (Python)")
    rows = classify_findings(results)
    st.table(rows)

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
st.caption(
    "This catalog lists major built-in exception families, OS/I/O subclasses, warnings, and asyncio/concurrency cases."
)

with st.expander("BaseException family (termination signals)"):
    st.markdown(
        "- **BaseException** – process termination signal\n"
        "- **SystemExit**\n- **KeyboardInterrupt**\n- **GeneratorExit**\n"
        "- **asyncio.CancelledError** (BaseException since 3.8; task cancellations)",
    )
    st.caption("Refs: built-in exceptions; asyncio exceptions docs.")  # see citations in chat

with st.expander("Exception family (catchable runtime errors)"):
    st.markdown(
        "- **ArithmeticError** → ZeroDivisionError, OverflowError, FloatingPointError\n"
        "- **AssertionError**\n- **AttributeError**\n- **BufferError**\n- **EOFError**\n"
        "- **ImportError** → ModuleNotFoundError\n- **LookupError** → IndexError, KeyError\n"
        "- **MemoryError**\n- **NameError** → UnboundLocalError\n- **OSError** (see next)\n"
        "- **ReferenceError**\n- **RuntimeError** → NotImplementedError, RecursionError\n"
        "- **StopIteration**, **StopAsyncIteration**\n- **SyntaxError** → IndentationError, TabError\n"
        "- **SystemError**\n- **TypeError**\n- **ValueError** → UnicodeError → UnicodeDecodeError, UnicodeEncodeError, UnicodeTranslateError"
    )

with st.expander("OS / I/O subclasses (OSError family)"):
    st.markdown(
        "- **OSError** (alias: IOError in Py3)\n"
        "- **BlockingIOError**, **ChildProcessError**\n"
        "- **ConnectionError** → BrokenPipeError, ConnectionAbortedError, ConnectionRefusedError, ConnectionResetError\n"
        "- **FileExistsError**, **FileNotFoundError**\n"
        "- **InterruptedError**\n- **IsADirectoryError**, **NotADirectoryError**\n"
        "- **PermissionError**, **ProcessLookupError**\n- **TimeoutError**"
    )

with st.expander("Warning classes (non-fatal alerts)"):
    st.markdown(
        "- **Warning** (base)\n- **UserWarning**\n- **DeprecationWarning**, **PendingDeprecationWarning**, **FutureWarning**\n"
        "- **SyntaxWarning**, **RuntimeWarning**, **ImportWarning**\n"
        "- **UnicodeWarning**, **BytesWarning**, **ResourceWarning**\n"
        "- **EncodingWarning** (PEP 597; default encoding warnings)"
    )

with st.expander("Async / concurrency specials"):
    st.markdown(
        "- **asyncio.CancelledError** (usually re-raise after cleanup)\n"
        "- **asyncio.InvalidStateError** (task/future misuse)\n"
        "- **concurrent.futures.CancelledError**"
    )

st.caption(
    "Authoritative references: Python built-in exceptions, warnings, asyncio exceptions, and OS/I/O notes. "
    "See the links in our chat message for details."
)

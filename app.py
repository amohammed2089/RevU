import os
import io
import csv
import json
import ast
import subprocess
import tempfile
from typing import List, Dict, Optional, Tuple

import streamlit as st

# -------------------- Page setup & styles --------------------
st.set_page_config(page_title="RevU — Your Code Reviewer (Enhanced)", page_icon="🤖", layout="wide")
st.markdown("""
<style>
h1, h2, h3 { letter-spacing: 0.2px; }
.small-muted { color:#6b6f76; font-size:0.95rem; }
.stButton > button {
  background: #2563eb !important; color: white !important; border: 0 !important;
  border-radius: 8px !important; font-weight: 600 !important; padding: 0.70rem 1.0rem !important;
}
.stButton > button:hover { filter: brightness(0.95); }
textarea, .stTextArea textarea { border-radius: 10px !important; }
div[data-testid="stFileUploader"] section[aria-label="base"] { border-radius: 10px !important; }
</style>
""", unsafe_allow_html=True)

# -------------------- Sidebar --------------------
with st.sidebar:
    st.header("Settings")
    language = st.selectbox("Language", ["Auto", "Python", "JavaScript / Other"], index=0)
    run_smoke = st.toggle("(Advanced) Attempt runtime smoke test (unsafe)", value=False,
                          help="Runs code in a subprocess with a short timeout. Use only for trusted snippets.")
    st.markdown(
        "<p class='small-muted'>Tools auto-detected: Ruff, mypy, Bandit, Black, isort, pydocstyle (best effort).</p>",
        unsafe_allow_html=True
    )

# -------------------- Title + subheader --------------------
st.markdown("## RevU — Enhanced Python Code Reviewer")
st.markdown(
    "<p class='small-muted'>Paste code or upload a file. Get unified findings across syntax, lint, types, security, formatting, imports, and docstrings.</p>",
    unsafe_allow_html=True
)

# -------------------- UI --------------------
col_img, col_ui = st.columns([0.7, 1.3], vertical_alignment="top")
with col_img:
    st.markdown("🧑‍💻")

with col_ui:
    code = st.text_area("Paste your code here", height=240, placeholder="# Paste code or upload a file below…")
    uploaded = st.file_uploader("…or upload a code file", type=None)
    if uploaded and not code:
        try:
            code = uploaded.read().decode("utf-8", errors="ignore")
        except Exception:
            code = ""
    run_clicked = st.button("🔎 Review Code", use_container_width=True)

# -------------------- Helpers --------------------
def _tmp_py(code_text: str) -> str:
    f = tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8")
    f.write(code_text); f.flush(); f.close()
    return f.name

def _run(cmd: List[str], cwd: Optional[str]=None, timeout: int=25) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"{cmd[0]}: not installed"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"

def _to_csv(rows: List[Dict], headers: List[str]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in headers})
    return buf.getvalue().encode("utf-8")

def _norm_row(source: str, rule: str, typ: str, msg: str,
              line: Optional[int], col: Optional[int], file: Optional[str],
              sev: Optional[str]=None) -> Dict:
    return {
        "Source": source, "Rule": rule or "", "Type": typ or "",
        "Message": msg or "", "Line": line or "", "Column": col or "",
        "File": file or "", "Severity/Level": sev or ""
    }

# -------------------- Built-in AST syntax check (always on) --------------------
def check_ast_syntax(code_text: str) -> List[Dict]:
    rows = []
    try:
        ast.parse(code_text)
    except SyntaxError as e:
        rows.append(_norm_row(
            "AST", "SyntaxError", "SyntaxError",
            f"{e.msg}", getattr(e, "lineno", None), getattr(e, "offset", None),
            "<input>"
        ))
    return rows

# -------------------- Ruff (lint) --------------------
def run_ruff(code_text: str) -> Tuple[List[Dict], Optional[str]]:
    tmp = _tmp_py(code_text)
    try:
        rc, out, err = _run(["ruff", "check", "--output-format=json", tmp])
        if rc == 127:
            return [], "Ruff not installed"
        if not out.strip():
            return [], None
        rows = []
        for item in json.loads(out):
            loc = item.get("location", {})
            rows.append(_norm_row(
                "Ruff", item.get("code", ""), "Lint/Style", item.get("message", ""),
                loc.get("row"), loc.get("column"), item.get("filename", "<input>")
            ))
        return rows, None
    finally:
        try: os.remove(tmp)
        except OSError: pass

# -------------------- mypy (types) --------------------
def run_mypy(code_text: str) -> Tuple[List[Dict], Optional[str]]:
    tmp = _tmp_py(code_text)
    try:
        rc, out, err = _run(["mypy", "--hide-error-context", "--no-pretty", "--show-column-numbers",
                             "--no-error-summary", "--strict", tmp])
        if rc == 127:
            return [], "mypy not installed"
        rows = []
        for line in (out + "\n" + err).splitlines():
            if tmp in line:
                try:
                    _, rest = line.split(f"{tmp}:", 1)
                    parts = rest.split(":", 3)
                    if len(parts) >= 3:
                        ln = int(parts[0]); col = int(parts[1]); rest2 = parts[2].strip()
                        typ = "Type" if "error" in rest2 else "Note"
                        msg = parts[3].strip() if len(parts) == 4 else rest2
                        code_tag = ""
                        if "[" in msg and "]" in msg:
                            code_tag = msg[msg.rfind("[")+1: msg.rfind("]")]
                        rows.append(_norm_row("mypy", code_tag, "TypeError/Typing", msg, ln, col, "<input>"))
                except Exception:
                    continue
        return rows, None
    finally:
        try: os.remove(tmp)
        except OSError: pass

# -------------------- Bandit (security) --------------------
def run_bandit(code_text: str) -> Tuple[List[Dict], Optional[str]]:
    tmp = _tmp_py(code_text)
    try:
        rc, out, err = _run(["bandit", "-f", "json", "-q", tmp])
        if rc == 127:
            return [], "Bandit not installed"
        rows = []
        if out.strip():
            data = json.loads(out)
            for issue in data.get("results", []):
                rows.append(_norm_row(
                    "Bandit", issue.get("test_id", ""), "Security", issue.get("issue_text", ""),
                    issue.get("line_number"), None, issue.get("filename"),
                    issue.get("issue_severity")
                ))
        return rows, None
    finally:
        try: os.remove(tmp)
        except OSError: pass

# -------------------- Black (formatting) --------------------
def run_black_check(code_text: str) -> Tuple[List[Dict], Optional[str]]:
    tmp = _tmp_py(code_text)
    try:
        rc, out, err = _run(["black", "--check", "--diff", tmp])
        if rc == 127:
            return [], "Black not installed"
        rows = []
        if rc not in (0,):
            rows.append(_norm_row("Black", "format", "Formatting", "File would be reformatted", None, None, "<input>"))
        return rows, None
    finally:
        try: os.remove(tmp)
        except OSError: pass

# -------------------- isort (imports) --------------------
def run_isort_check(code_text: str) -> Tuple[List[Dict], Optional[str]]:
    tmp = _tmp_py(code_text)
    try:
        rc, out, err = _run(["isort", "--check-only", "--diff", tmp])
        if rc == 127:
            return [], "isort not installed"
        rows = []
        if rc not in (0,):
            rows.append(_norm_row("isort", "imports", "Import Order", "Imports not correctly sorted", None, None, "<input>"))
        return rows, None
    finally:
        try: os.remove(tmp)
        except OSError: pass

# -------------------- pydocstyle (docstrings) --------------------
def run_pydocstyle(code_text: str) -> Tuple[List[Dict], Optional[str]]:
    tmp = _tmp_py(code_text)
    try:
        rc, out, err = _run(["pydocstyle", tmp])
        if rc == 127:
            return [], "pydocstyle not installed"
        rows = []
        for line in out.splitlines():
            if ":" in line and tmp in line:
                try:
                    _, rest = line.split(f"{tmp}:", 1)
                    ln = int(rest.split()[0])
                    code_tag = rest.split()[-1].split(":")[0] if ":" in rest else "Dxxx"
                    rows.append(_norm_row("pydocstyle", code_tag, "Docstring", line.strip(), ln, None, "<input>"))
                except Exception:
                    continue
        return rows, None
    finally:
        try: os.remove(tmp)
        except OSError: pass

# -------------------- Optional smoke runtime test --------------------
def run_smoke_test(code_text: str) -> Tuple[List[Dict], Optional[str]]:
    if not run_smoke:
        return [], None
    tmp = _tmp_py(code_text)
    try:
        rc, out, err = _run(["python", "-I", "-X", "faulthandler", tmp], timeout=3)
        rows = []
        if rc != 0:
            msg = (err or out).strip()
            first = msg.splitlines()[0] if msg else "Runtime error"
            rows.append(_norm_row("Runtime", "", "Runtime", first, None, None, "<input>"))
        return rows, None
    finally:
        try: os.remove(tmp)
        except OSError: pass

# -------------------- Orchestrate checks --------------------
def analyze(code_text: str) -> Dict[str, List[Dict]]:
    results = {
        "AST": check_ast_syntax(code_text),
        "Ruff": run_ruff(code_text)[0],
        "mypy": run_mypy(code_text)[0],
        "Bandit": run_bandit(code_text)[0],
        "Black": run_black_check(code_text)[0],
        "isort": run_isort_check(code_text)[0],
        "pydocstyle": run_pydocstyle(code_text)[0],
        "Runtime": run_smoke_test(code_text)[0],
    }
    return results

def flatten(all_results: Dict[str, List[Dict]]) -> List[Dict]:
    rows: List[Dict] = []
    for v in all_results.values():
        rows.extend(v)
    return rows

# -------------------- Run review --------------------
if run_clicked:
    if not code or not code.strip():
        st.warning("Please paste code or upload a file first.")
        st.stop()

    lang = language
    if lang == "Auto":
        if uploaded and uploaded.name.endswith(".py"):
            lang = "Python"
        elif any(tok in code for tok in ["import ", "def ", "class "]):
            lang = "Python"
        else:
            lang = "JavaScript / Other"

    if lang != "Python":
        st.warning("This enhanced checker focuses on Python. Paste Python code for full results.")
        st.stop()

    st.info("Running checks (AST, Ruff, mypy, Bandit, Black, isort, pydocstyle" +
            (", Runtime smoke" if run_smoke else "") + ") …")

    all_results = analyze(code)
    combined = flatten(all_results)

    if not combined:
        st.success("✅ No issues reported by the enabled tools.")
    else:
        st.subheader("All Findings (Unified)")
        st.dataframe(combined, use_container_width=True)

        for tool, rows in all_results.items():
            st.markdown(f"### {tool} findings")
            if rows:
                st.table(rows)
                st.download_button(
                    label=f"⬇️ Download {tool} findings (CSV)",
                    data=_to_csv(rows, ["Source","Rule","Type","Message","Line","Column","File","Severity/Level"]),
                    file_name=f"{tool.lower()}_findings.csv",
                    mime="text/csv"
                )
            else:
                st.caption(f"No {tool} findings or tool not installed / not applicable.")

        st.download_button(
            label="⬇️ Download All Findings (CSV)",
            data=_to_csv(combined, ["Source","Rule","Type","Message","Line","Column","File","Severity/Level"]),
            file_name="all_findings.csv",
            mime="text/csv"
        )

# -------------------- References --------------------
st.markdown("## References")
st.markdown("- Python exceptions: https://docs.python.org/3/library/exceptions.html")
st.markdown("- Ruff (lint): https://docs.astral.sh/ruff/")
st.markdown("- mypy (types): https://mypy.readthedocs.io/en/stable/")
st.markdown("- Bandit (security): https://bandit.readthedocs.io/en/latest/")
st.markdown("- Black (format): https://black.readthedocs.io/en/stable/")
st.markdown("- isort (imports): https://pycqa.github.io/isort/")
st.markdown("- pydocstyle (docstrings): https://www.pydocstyle.org/en/stable/")

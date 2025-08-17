import os
import io
import csv
import json
import ast
import tokenize
import subprocess
import tempfile
from typing import List, Dict, Optional, Tuple

import streamlit as st

# -------------------- Page setup & styles --------------------
st.set_page_config(page_title="RevU — Your Code Reviewer (Enhanced+)", page_icon="🤖", layout="wide")
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
                          help="Runs code in a subprocess with a short timeout. Only for trusted snippets.")
    st.markdown(
        "<p class='small-muted'>Tools: AST, tokenize, parso*, Ruff, mypy, Bandit, pydocstyle, (optional) Runtime</p>",
        unsafe_allow_html=True
    )

# -------------------- Title --------------------
st.markdown("## RevU — Enhanced Python Code Reviewer (Multi-Syntax)")
st.caption("Reports multiple syntax issues via parso + tokenize, plus lint, types, security, docstrings, and optional runtime errors.")

# -------------------- UI --------------------
code = st.text_area("Paste your Python code here", height=240, placeholder="# Paste code or upload a file…")
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

# -------------------- Multi-syntax detectors --------------------
def check_ast_syntax(code_text: str) -> List[Dict]:
    rows = []
    try:
        ast.parse(code_text)
    except SyntaxError as e:
        rows.append(_norm_row("AST", "SyntaxError", "SyntaxError",
                              f"{e.msg}", getattr(e, "lineno", None), getattr(e, "offset", None),
                              "<input>"))
    return rows

def check_tokenize(code_text: str) -> List[Dict]:
    """Detect IndentationError/TabError style issues using tokenize."""
    rows = []
    try:
        _ = list(tokenize.generate_tokens(io.StringIO(code_text).readline))
    except (tokenize.IndentationError, IndentationError) as e:
        # IndentationError shape can vary; best effort extract
        msg = getattr(e, "msg", "Indentation error")
        (ln, col) = (getattr(e, "lineno", None), getattr(e, "offset", None))
        rows.append(_norm_row("tokenize", "IndentationError", "SyntaxError", msg, ln, col, "<input>"))
    except (tokenize.TokenError, TabError) as e:
        msg = str(e) or "Token error"
        rows.append(_norm_row("tokenize", "TokenError", "SyntaxError", msg, None, None, "<input>"))
    return rows

def check_parso(code_text: str) -> Tuple[List[Dict], Optional[str]]:
    """Use parso tolerant parser to enumerate multiple syntax issues."""
    try:
        import parso  # type: ignore
    except Exception:
        return [], "parso not installed"
    rows: List[Dict] = []
    try:
        grammar = parso.load_grammar()  # auto-selects current Python
        module = grammar.parse(code_text, error_recovery=True)
        for err in module.iter_errors():
            # parso error has .message and .start_pos (line, column)
            msg = getattr(err, "message", "Syntax issue")
            ln, col = getattr(err, "start_pos", (None, None))
            rows.append(_norm_row("parso", "SyntaxError", "SyntaxError", msg, ln, col, "<input>"))
    except Exception as e:
        rows.append(_norm_row("parso", "", "Internal", f"parso failed: {e}", None, None, "<input>"))
    return rows, None

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
                        msg = parts[3].strip() if len(parts) == 4 else rest2
                        code_tag = ""
                        if "[" in msg and "]" in msg:
                            code_tag = msg[msg.rfind("[")+1: msg.rfind("]")]
                        rows.append(_norm_row("mypy", code_tag or "mypy", "TypeError/Typing", msg, ln, col, "<input>"))
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

# -------------------- Runtime smoke test --------------------
def run_smoke_test(code_text: str) -> Tuple[List[Dict], Optional[str]]:
    rows: List[Dict] = []
    if not run_smoke:
        return rows, None
    # Only attempt if it compiles (to avoid SyntaxError explosions)
    try:
        compile(code_text, "<input>", "exec")
    except SyntaxError:
        return rows, "Skipped (does not compile)"
    tmp = _tmp_py(code_text)
    try:
        rc, out, err = _run(["python", "-I", "-X", "faulthandler", tmp], timeout=3)
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
        "tokenize": check_tokenize(code_text),
        "parso": check_parso(code_text)[0],   # tolerant, multi-syntax
        "Ruff": run_ruff(code_text)[0],
        "mypy": run_mypy(code_text)[0],
        "Bandit": run_bandit(code_text)[0],
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
        st.warning("This checker focuses on Python.")
        st.stop()

    st.info("Running: AST, tokenize, parso*, Ruff, mypy, Bandit, pydocstyle"
            + (", Runtime smoke" if run_smoke else "") + " …")

    all_results = analyze(code)
    combined = flatten(all_results)

    if not combined:
        st.success("✅ No issues reported by the enabled tools.")
    else:
        st.subheader("All Findings (Unified)")
        st.dataframe(combined, use_container_width=True)

        # Per-tool breakdown + CSV
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
st.markdown("- Python built-in exceptions (SyntaxError/IndentationError/TabError): https://docs.python.org/3/library/exceptions.html")
st.markdown("- tokenize module (token stream & indentation errors): https://docs.python.org/3/library/tokenize.html")
st.markdown("- parso tolerant parser: https://parso.readthedocs.io/en/latest/")
st.markdown("- Ruff (lint/format/imports): https://docs.astral.sh/ruff/")
st.markdown("- mypy (static typing): https://mypy.readthedocs.io/en/stable/")
st.markdown("- Bandit (security): https://bandit.readthedocs.io/en/latest/")
st.markdown("- pydocstyle (docstrings): https://www.pydocstyle.org/en/stable/")

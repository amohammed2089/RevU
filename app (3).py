python
import os
import io
import re
import csv
import json
import ast
import difflib
import tokenize
import subprocess
import tempfile
from typing import List, Dict, Optional, Tuple

import streamlit as st
from PIL import Image

# ==================== Page setup & hero ====================
st.set_page_config(page_title="RevU — Your Code Reviewer (Pro)", page_icon="🤖", layout="wide")

def load_robot_image() -> Optional[str]:
    """Find a bundled robot.png (repo root or ./assets or /mnt/data) and return its path, else None."""
    candidates = [
        "robot.png",
        os.path.join("assets", "robot.png"),
        "/mnt/data/robot.png",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

with st.container():
    left, mid = st.columns([1, 6])
    with left:
        img_path = load_robot_image()
        if img_path:
            try:
                st.image(Image.open(img_path), use_column_width=True)
            except Exception:
                st.image(img_path, use_column_width=True)
        else:
            st.write("🤖")
    with mid:
        st.markdown("# RevU — Enhanced Python Code Reviewer")
        st.caption(
            "Detects syntax (AST/tokenize/parso), lint/style (Ruff), formatting (Black), "
            "imports (isort), typing (mypy), security (Bandit), docstrings (pydocstyle), "
            "code smells (Pylint), complexity (Radon), dead code (Vulture), and optional runtime errors."
        )

# ==================== Sidebar ====================
with st.sidebar:
    st.header("Settings")
    language = st.selectbox("Language", ["Auto", "Python", "JavaScript / Other"], index=0)
    run_smoke = st.toggle(
        "(Advanced) Attempt runtime smoke test (unsafe)",
        value=False,
        help="Runs code in a subprocess with a short timeout. Only for trusted snippets.",
    )
    apply_fixes_before_runtime = st.toggle(
        "(Advanced) Apply safe quick fixes before runtime",
        value=False,
        help="Best-effort syntax-only fixes (e.g., missing ':' on block headers) so smoke test can run.",
    )
    warnings_as_errors = st.toggle(
        "Treat Python warnings as errors in runtime smoke",
        value=False,
        help="Runs with -W error so Python warnings become runtime failures."
    )
    st.markdown(
        "<p style='color:#6b6f76'>Tools: AST, tokenize, parso*, Ruff, Black, isort, mypy, Bandit, pydocstyle, "
        "Pylint, Radon, Vulture, optional Runtime</p>",
        unsafe_allow_html=True,
    )

# ==================== UI ====================
code = st.text_area("Paste your Python code here", height=260, placeholder="# Paste code or upload a file…")
uploaded = st.file_uploader("…or upload a code file", type=None)
if uploaded and not code:
    try:
        code = uploaded.read().decode("utf-8", errors="ignore")
    except Exception:
        code = ""
run_clicked = st.button("🔎 Review Code", use_container_width=True)

# ==================== Helpers ====================
def _tmp_py(code_text: str) -> str:
    f = tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8")
    f.write(code_text)
    f.flush()
    f.close()
    return f.name

def _run(cmd: List[str], cwd: Optional[str] = None, timeout: int = 30) -> Tuple[int, str, str]:
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
              sev: Optional[str] = None) -> Dict:
    return {
        "Source": source, "Rule": rule or "", "Type": typ or "", "Message": msg or "",
        "Line": line or "", "Column": col or "", "File": file or "", "Severity/Level": sev or "",
    }

# ==================== Safe quick fixes (syntax-only) ====================
_BLOCK_HEADERS = (
    r"^\\s*(def\\s+\\w+\\s*\\(.*\\)\\s*)",
    r"^\\s*(class\\s+\\w+\\s*)",
    r"^\\s*(if\\s+.*)",
    r"^\\s*(elif\\s+.*)",
    r"^\\s*(else\\s*)",
    r"^\\s*(for\\s+.*)",
    r"^\\s*(while\\s+.*)",
    r"^\\s*(try\\s*)",
    r"^\\s*(except(\\s+.*)?\\s*)",
    r"^\\s*(finally\\s*)",
    r"^\\s*(with\\s+.*)",
)

def _needs_colon(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    no_comment = stripped.split("#", 1)[0].rstrip()
    return not no_comment.endswith(":")

def apply_quick_fixes(original: str) -> Tuple[str, List[int]]:
    lines = original.splitlines()
    edited: List[int] = []
    header_regexes = [re.compile(p) for p in _BLOCK_HEADERS]
    for idx, line in enumerate(lines):
        for rx in header_regexes:
            if rx.match(line):
                if _needs_colon(line):
                    lines[idx] = line.rstrip() + ":  # [AUTO-FIXED]"
                    edited.append(idx + 1)
                break
    fixed = "\\n".join(lines)
    if original.endswith("\\n") and not fixed.endswith("\\n"):
        fixed += "\\n"
    return fixed, edited

# ==================== Syntax detectors ====================
def check_ast_syntax(code_text: str) -> List[Dict]:
    rows: List[Dict] = []
    try:
        ast.parse(code_text)
    except SyntaxError as e:
        rows.append(_norm_row("AST", "SyntaxError", "SyntaxError", f"{e.msg}",
                              getattr(e, "lineno", None), getattr(e, "offset", None), "<input>"))
    return rows

def check_tokenize(code_text: str) -> List[Dict]:
    rows: List[Dict] = []
    try:
        _ = list(tokenize.generate_tokens(io.StringIO(code_text).readline))
    except (IndentationError, TabError) as e:
        msg = getattr(e, "msg", str(e)) or "Indentation error"
        ln, col = getattr(e, "lineno", None), getattr(e, "offset", None)
        rows.append(_norm_row("tokenize", "IndentationError", "SyntaxError", msg, ln, col, "<input>"))
    except tokenize.TokenError as e:
        rows.append(_norm_row("tokenize", "TokenError", "SyntaxError", str(e), None, None, "<input>"))
    return rows

def check_parso(code_text: str) -> Tuple[List[Dict], Optional[str]]:
    try:
        import parso  # type: ignore
    except Exception:
        return [], "parso not installed"
    rows: List[Dict] = []
    try:
        grammar = parso.load_grammar()
        module = grammar.parse(code_text, error_recovery=True)
        for err in module.iter_errors():
            msg = getattr(err, "message", "Syntax issue")
            ln, col = getattr(err, "start_pos", (None, None))
            rows.append(_norm_row("parso", "SyntaxError", "SyntaxError", msg, ln, col, "<input>"))
    except Exception as e:
        rows.append(_norm_row("parso", "", "Internal", f"parso failed: {e}", None, None, "<input>"))
    return rows, None

# ==================== External tools ====================
def run_ruff(code_text: str) -> Tuple[List[Dict], Optional[str]]:
    tmp = _tmp_py(code_text)
    try:
        rc, out, err = _run(["ruff", "check", "--output-format=json", tmp])
        if rc == 127:
            return [], "Ruff not installed"
        if not out.strip():
            return [], None
        rows: List[Dict] = []
        payload = json.loads(out)
        for item in payload:
            loc = item.get("location", {})
            rows.append(_norm_row("Ruff", item.get("code", ""), "Lint/Style",
                                  item.get("message", ""), loc.get("row"), loc.get("column"),
                                  item.get("filename", "<input>")))
        return rows, None
    finally:
        try: os.remove(tmp)
        except OSError: pass

def run_black_check(code_text: str) -> Tuple[List[Dict], Optional[str]]:
    tmp = _tmp_py(code_text)
    try:
        rc, out, err = _run(["black", "--check", "--diff", tmp])
        if rc == 127:
            return [], "Black not installed"
        rows: List[Dict] = []
        if rc != 0:
            rows.append(_norm_row("Black", "format", "Formatting", "File would be reformatted",
                                  None, None, "<input>"))
        return rows, None
    finally:
        try: os.remove(tmp)
        except OSError: pass

def run_isort_check(code_text: str) -> Tuple[List[Dict], Optional[str]]:
    tmp = _tmp_py(code_text)
    try:
        rc, out, err = _run(["isort", "--check-only", "--diff", tmp])
        if rc == 127:
            return [], "isort not installed"
        rows: List[Dict] = []
        if rc != 0:
            rows.append(_norm_row("isort", "imports", "Import Order", "Imports not correctly sorted",
                                  None, None, "<input>"))
        return rows, None
    finally:
        try: os.remove(tmp)
        except OSError: pass

def run_mypy(code_text: str) -> Tuple[List[Dict], Optional[str]]:
    tmp = _tmp_py(code_text)
    try:
        rc, out, err = _run(["mypy", "--hide-error-context", "--no-pretty",
                             "--show-column-numbers", "--no-error-summary", "--strict", tmp])
        if rc == 127:
            return [], "mypy not installed"
        rows: List[Dict] = []
        for line in (out + "\\n" + err).splitlines():
            if tmp in line:
                try:
                    _, rest = line.split(f"{tmp}:", 1)
                    parts = rest.split(":", 3)
                    if len(parts) >= 3:
                        ln = int(parts[0])
                        col = int(parts[1])
                        rest2 = parts[2].strip()
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

def run_bandit(code_text: str) -> Tuple[List[Dict], Optional[str]]:
    tmp = _tmp_py(code_text)
    try:
        rc, out, err = _run(["bandit", "-f", "json", "-q", tmp])
        if rc == 127:
            return [], "Bandit not installed"
        rows: List[Dict] = []
        if out.strip():
            try:
                data = json.loads(out)
                for issue in data.get("results", []):
                    rows.append(_norm_row("Bandit", issue.get("test_id", ""), "Security",
                                          issue.get("issue_text", ""),
                                          issue.get("line_number"), None, issue.get("filename"),
                                          issue.get("issue_severity")))
            except Exception:
                pass
        return rows, None
    finally:
        try: os.remove(tmp)
        except OSError: pass

def run_pydocstyle(code_text: str) -> Tuple[List[Dict], Optional[str]]:
    tmp = _tmp_py(code_text)
    try:
        rc, out, err = _run(["pydocstyle", tmp])
        if rc == 127:
            return [], "pydocstyle not installed"
        rows: List[Dict] = []
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

def run_pylint(code_text: str) -> Tuple[List[Dict], Optional[str]]:
    tmp = _tmp_py(code_text)
    try:
        rc, out, err = _run(["pylint", "--output-format=json", "--score=n", tmp], timeout=60)
        if rc == 127:
            return [], "pylint not installed"
        rows: List[Dict] = []
        if out.strip():
            try:
                data = json.loads(out)
                for item in data:
                    rows.append(_norm_row("Pylint", item.get("symbol", ""), "Code Smell",
                                          item.get("message", ""),
                                          item.get("line"), item.get("column"), item.get("path"),
                                          item.get("type")))
            except Exception:
                pass
        return rows, None
    finally:
        try: os.remove(tmp)
        except OSError: pass

def run_radon_complexity(code_text: str) -> Tuple[List[Dict], Optional[str]]:
    tmp = _tmp_py(code_text)
    try:
        rc, out, err = _run(["radon", "cc", "-j", tmp])
        if rc == 127:
            return [], "radon not installed"
        rows: List[Dict] = []
        if out.strip():
            try:
                data = json.loads(out)
                for fn, blocks in data.items():
                    for b in blocks:
                        rows.append(_norm_row("Radon", f"CC {b.get('rank')}", "Complexity",
                                              f"{b.get('name')} has complexity {b.get('complexity')}",
                                              b.get("lineno"), None, fn))
            except Exception:
                pass
        return rows, None
    finally:
        try: os.remove(tmp)
        except OSError: pass

def run_vulture(code_text: str) -> Tuple[List[Dict], Optional[str]]:
    tmp = _tmp_py(code_text)
    try:
        rc, out, err = _run(["vulture", tmp, "--min-confidence", "0", "--json"])
        if rc == 127:
            return [], "vulture not installed"
        rows: List[Dict] = []
        if out.strip():
            try:
                data = json.loads(out)
                for item in data:
                    rows.append(_norm_row("Vulture", item.get("type", ""), "Dead Code",
                                          item.get("message", ""),
                                          item.get("line"), None, item.get("filename"),
                                          f"conf={item.get('confidence')}"))
            except Exception:
                pass
        return rows, None
    finally:
        try: os.remove(tmp)
        except OSError: pass

# ==================== Runtime smoke (optional) ====================
def run_smoke_test(code_text: str, maybe_fix: bool, treat_warnings_as_errors: bool) -> Tuple[List[Dict], Optional[str], Optional[str], Optional[str]]:
    rows: List[Dict] = []
    note: Optional[str] = None
    used_code = code_text
    diff_text: Optional[str] = None

    def _can_compile(src: str) -> bool:
        try:
            compile(src, "<input>", "exec")
            return True
        except SyntaxError:
            return False

    if not run_smoke:
        return rows, "Runtime test disabled", None, None

    if _can_compile(used_code):
        pass
    elif maybe_fix:
        fixed, edited = apply_quick_fixes(used_code)
        if edited and _can_compile(fixed):
            diff = difflib.unified_diff(used_code.splitlines(True), fixed.splitlines(True),
                                        fromfile="original", tofile="fixed")
            diff_text = "".join(diff)
            used_code = fixed
            note = f"Applied safe quick fixes on lines: {edited}"
        else:
            return rows, "Skipped runtime (does not compile, even after quick fixes)", None, None
    else:
        return rows, "Skipped runtime (does not compile; enable quick fixes to attempt)", None, None

    tmp = _tmp_py(used_code)
    try:
        cmd = ["python"]
        if treat_warnings_as_errors:
            cmd += ["-W", "error"]
        cmd += ["-I", "-X", "faulthandler", tmp]
        rc, out, err = _run(cmd, timeout=3)
        if rc != 0:
            msg = (err or out).strip()
            first = msg.splitlines()[0] if msg else "Runtime error"
            rows.append(_norm_row("Runtime", "", "Runtime", first, None, None, "<input>"))
        return rows, note, used_code, diff_text
    finally:
        try: os.remove(tmp)
        except OSError: pass

# ==================== Orchestrate checks ====================
def analyze(code_text: str) -> Dict[str, List[Dict]]:
    parso_rows, parso_note = check_parso(code_text)
    if parso_note:
        st.caption(f"parso: {parso_note}")
    results: Dict[str, List[Dict]] = {
        "AST": check_ast_syntax(code_text),
        "tokenize": check_tokenize(code_text),
        "parso": parso_rows,
        "Ruff": run_ruff(code_text)[0],
        "Black": run_black_check(code_text)[0],
        "isort": run_isort_check(code_text)[0],
        "mypy": run_mypy(code_text)[0],
        "Bandit": run_bandit(code_text)[0],
        "pydocstyle": run_pydocstyle(code_text)[0],
        "Pylint": run_pylint(code_text)[0],
        "Radon": run_radon_complexity(code_text)[0],
        "Vulture": run_vulture(code_text)[0],
    }
    return results

def flatten(all_results: Dict[str, List[Dict]]) -> List[Dict]:
    rows: List[Dict] = []
    for v in all_results.values():
        rows.extend(v)
    return rows

def summarize(all_rows: List[Dict]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for r in all_rows:
        src = r.get("Source", "Unknown")
        counts[src] = counts.get(src, 0) + 1
    return counts

# ==================== Run review ====================
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

    st.info(
        "Running: AST, tokenize, parso*, Ruff, Black, isort, mypy, Bandit, pydocstyle, Pylint, Radon, Vulture"
        + (", Runtime smoke" if run_smoke else "")
        + " …"
    )

    all_results = analyze(code)
    runtime_rows, runtime_note, used_code, diff_text = run_smoke_test(
        code, apply_fixes_before_runtime, warnings_as_errors
    )
    all_results["Runtime"] = runtime_rows

    combined = flatten(all_results)

    st.subheader("All Findings (Unified)")
    if combined:
        st.dataframe(combined, use_container_width=True)
    else:
        st.success("✅ No issues reported by the enabled tools.")

    # Summary chips
    with st.expander("Show summary by tool"):
        counts = summarize(combined)
        st.json(counts)

    # Per-tool breakdown + CSV
    for tool, rows in all_results.items():
        st.markdown(f"### {tool} findings")
        if rows:
            st.table(rows)
            st.download_button(
                label=f"⬇️ Download {tool} findings (CSV)",
                data=_to_csv(rows, ["Source", "Rule", "Type", "Message", "Line", "Column", "File", "Severity/Level"]),
                file_name=f"{tool.lower()}_findings.csv",
                mime="text/csv",
            )
        else:
            st.caption(f"No {tool} findings or tool not installed / not applicable.")

    st.download_button(
        label="⬇️ Download All Findings (CSV)",
        data=_to_csv(combined, ["Source", "Rule", "Type", "Message", "Line", "Column", "File", "Severity/Level"]),
        file_name="all_findings.csv",
        mime="text/csv",
    )

    # Runtime notes + optional diff & fixed code download
    st.markdown("### Runtime test")
    if runtime_note:
        st.info(runtime_note)
    if diff_text:
        with st.expander("Show quick-fix diff (unified)"):
            st.code(diff_text, language="diff")
    if used_code and diff_text:
        st.download_button(
            "⬇️ Download quick-fixed code",
            used_code.encode("utf-8"),
            file_name="fixed_input.py",
            mime="text/x-python",
        )

# ==================== References ====================
st.markdown("## References")
st.markdown("- Python built-in exceptions: https://docs.python.org/3/library/exceptions.html")
st.markdown("- Python tokenize module: https://docs.python.org/3/library/tokenize.html")
st.markdown("- Parso tolerant parser: https://parso.readthedocs.io/en/latest/")
st.markdown("- Ruff (lint/format/imports): https://docs.astral.sh/ruff/")
st.markdown("- Black (formatter): https://black.readthedocs.io/en/stable/")
st.markdown("- isort (import sorting): https://pycqa.github.io/isort/")
st.markdown("- mypy (static typing): https://mypy.readthedocs.io/en/stable/")
st.markdown("- Bandit (security): https://bandit.readthedocs.io/en/latest/")
st.markdown("- pydocstyle (docstrings): https://www.pydocstyle.org/en/stable/")
st.markdown("- Pylint: https://pylint.readthedocs.io/")
st.markdown("- Radon (complexity): https://radon.readthedocs.io/")
st.markdown("- Vulture (dead code): https://vulture.readthedocs.io/")
st.markdown("- Streamlit st.image: https://docs.streamlit.io/library/api-reference/media/st.image")
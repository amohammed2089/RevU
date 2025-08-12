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

# ===================== Page setup =====================
st.set_page_config(page_title="RevU — Your AI Code Reviewer", page_icon="🤖", layout="wide")

# ===================== ✨ Ultra-UI CSS (AI effects, glass, no-scroll) =====================
AI_CSS = """
<style>
html, body, [data-testid="stAppViewContainer"] {
  height: 100%;
  margin: 0 !important;
  padding: 0 !important;
  overflow: hidden !important; /* No right-side scroll */
}
#MainMenu, header[data-testid="stHeader"], footer, [data-testid="stToolbar"] { display: none !important; }
[data-testid="stAppViewContainer"] > .main, .block-container {
  padding: 0 !important;
  margin: 0 auto !important;
  max-width: 1200px !important;
  min-height: 100vh !important;
  display: flex; flex-direction: column; justify-content: center;
}
body:before, body:after {
  content:""; position: fixed; inset: -20%;
  z-index: -3;
  background: radial-gradient(35% 35% at 20% 20%, rgba(0,140,255,0.25), transparent 60%),
              radial-gradient(40% 40% at 85% 30%, rgba(255,0,200,0.18), transparent 60%),
              radial-gradient(30% 30% at 50% 80%, rgba(0,255,170,0.18), transparent 60%);
  filter: blur(40px);
  animation: floatBlobs 18s ease-in-out infinite alternate;
}
@keyframes floatBlobs {
  0%   { transform: translate3d(0, -10px, 0) scale(1);   }
  100% { transform: translate3d(0, 10px, 0)  scale(1.05);}
}
body:after {
  z-index: -2;
  background-image:
    linear-gradient(rgba(255,255,255,0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.06) 1px, transparent 1px);
  background-size: 28px 28px, 28px 28px;
  mask-image: radial-gradient(60% 60% at 50% 50%, rgba(0,0,0,.35), transparent 70%);
  animation: pulseGrid 12s ease-in-out infinite;
}
@keyframes pulseGrid { 0%{opacity:.45} 50%{opacity:.65} 100%{opacity:.45} }

h1, h2 { letter-spacing: .2px; }
.ai-title {
  font-size: clamp(28px, 4vw, 40px);
  font-weight: 800; line-height: 1.1;
  background: linear-gradient(90deg, #fff, #a0e9ff 30%, #f6a1ff 60%, #c0fff3 90%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
  text-shadow: 0 0 18px rgba(160,233,255,0.45);
}
.hero {
  display: grid; grid-template-columns: 0.9fr 1.1fr; gap: 26px; align-items: stretch;
  width: 100%; height: min(84vh, 780px); margin: 18px auto 10px; padding: 8px 18px; box-sizing: border-box;
}
.card {
  position: relative; height: 100%;
  background: radial-gradient(120% 120% at 50% 0%, rgba(255,255,255,0.20), rgba(255,255,255,0.08));
  border: 1px solid rgba(255,255,255,0.20); border-radius: 18px;
  box-shadow: 0 10px 40px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.2);
  backdrop-filter: blur(14px) saturate(140%); -webkit-backdrop-filter: blur(14px) saturate(140%);
  overflow: hidden;
}
.card:before {
  content:""; position:absolute; inset:-2px; border-radius: 20px;
  background: conic-gradient(from 180deg at 50% 50%, rgba(0,153,255,.6), rgba(255,0,200,.6), rgba(0,255,170,.6), rgba(0,153,255,.6));
  filter: blur(24px); opacity: .18; z-index: 0;
}
.card-inner { position: relative; z-index: 1; height: 100%; padding: 18px; display:flex; flex-direction:column; }
.bot-wrap { flex:1; display:flex; align-items:center; justify-content:center; position:relative; }
.bot-wrap:after {
  content:""; position:absolute; width:65%; aspect-ratio:1; border-radius:50%;
  background: radial-gradient(circle at 50% 50%, rgba(160,233,255,.65), transparent 60%);
  filter: blur(40px); animation: breathe 4s ease-in-out infinite;
}
@keyframes breathe { 0%{transform:scale(0.96)} 50%{transform:scale(1.04)} 100%{transform:scale(0.96)} }
.right-card .stTextArea textarea {
  height: 44vh !important; min-height: 240px !important;
  resize: none !important; border-radius: 12px !important;
}
.right-card [data-testid="stFileUploader"] section[aria-label="base"] { border-radius: 12px !important; }
.stButton > button {
  background: linear-gradient(90deg, #ff6b6b, #ff3b3b) !important; color: #fff !important;
  border: 0 !important; border-radius: 12px !important; font-weight: 700 !important;
  padding: .9rem 1.2rem !important; box-shadow: 0 6px 18px rgba(255,59,59,.35);
  transition: transform .08s ease, filter .12s ease;
}
.stButton > button:hover { filter: brightness(.96); transform: translateY(-1px); }
.stButton > button:active { transform: translateY(0); }
.small-muted { color:#d7dbe0; font-size:.96rem; opacity:.9; }
section[data-testid="stSidebar"] > div { padding-top: 14px; }
section[data-testid="stSidebar"] .block-container { padding: 14px 14px 18px !important; }
[data-testid="stTable"] table { font-size: .92rem; }
[data-testid="stHorizontalBlock"] { gap: 26px !important; }
details, [data-testid="stExpander"] { max-height: 28vh; overflow: auto; }
h1, h2, h3, label, p, span, div { color: #f0f3f7; }

/* ---- Animated "Analyzing…" pill ---- */
.ai-pill {
  display:inline-flex; align-items:center; gap:10px; padding:8px 12px;
  border-radius:999px; background:rgba(255,255,255,0.10); border:1px solid rgba(255,255,255,0.18);
  backdrop-filter: blur(10px);
}
.ai-dot {
  width:8px; height:8px; border-radius:50%;
  background: #a0e9ff; box-shadow: 0 0 12px #a0e9ff;
  animation: aiPulse 1s ease-in-out infinite;
}
.ai-dot:nth-child(2){ animation-delay: .15s; }
.ai-dot:nth-child(3){ animation-delay: .3s; }
@keyframes aiPulse {
  0%{transform:scale(1); opacity:.4} 
  50%{transform:scale(1.6); opacity:1} 
  100%{transform:scale(1); opacity:.4}
}
</style>
"""
st.markdown(AI_CSS, unsafe_allow_html=True)

# ===================== Sidebar =====================
with st.sidebar:
    st.header("Settings")
    language = st.selectbox("Language", ["Auto", "Python", "JavaScript / Other"], index=0)
    run_runtime = st.toggle(
        "Run runtime checks (sandboxed subprocess)",
        value=False,
        help=("Executes code in an isolated Python subprocess with -I, -X dev, warnings enabled, tmp cwd, and near-empty env. "
              "Enable only for trusted Python snippets.")
    )
    show_warnings = st.toggle("Report warnings (Deprecation/Resource/Encoding/etc.)", value=True)
    use_ai = st.toggle("AI suggestions (requires OPENAI_API_KEY)", value=False)
    st.markdown(
        "<p class='small-muted'>Tip: Python ➜ compile check → optional sandboxed run → Ruff → security scan → (optional) AI.</p>",
        unsafe_allow_html=True
    )

# ===================== Title =====================
st.markdown(
    '<div style="padding: 10px 22px 0;">'
    '<div class="ai-title">RevU — Your AI Code Reviewer</div>'
    '<p class="small-muted" style="margin:.25rem 0 0;">Paste code or upload a file. '
    'RevU catches compile errors, runtime exceptions, warnings, security smells, and Ruff issues.</p>'
    '</div>',
    unsafe_allow_html=True
)

# ===================== Hero (2 cards, fixed height, no page scroll) =====================
st.markdown('<div class="hero">', unsafe_allow_html=True)

# Left: bot / visual
st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown('<div class="card-inner">', unsafe_allow_html=True)
st.markdown('<div class="bot-wrap">', unsafe_allow_html=True)
try:
    if os.path.exists("robot.png"):
        st.image(Image.open("robot.png"), use_container_width=True)
    else:
        st.markdown("🧑‍💻", unsafe_allow_html=True)
except Exception:
    st.markdown("🧑‍💻", unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)  # bot-wrap
st.markdown('</div>', unsafe_allow_html=True)  # card-inner
st.markdown('</div>', unsafe_allow_html=True)  # card

# Right: code UI
st.markdown('<div class="card right-card">', unsafe_allow_html=True)
st.markdown('<div class="card-inner">', unsafe_allow_html=True)

label = "Paste your code here – sit back and let RevU catch every code flaw"
code = st.text_area(label, height=420, placeholder="# Paste code or upload a file below…")

uploaded = st.file_uploader("…or upload a code file", type=None)
filename = None
if uploaded and not code:
    try:
        code = uploaded.read().decode("utf-8", errors="ignore")
        filename = uploaded.name
    except Exception:
        code = ""

# 🔁 Animated “Analyzing…” area + progress bar placeholders
status_container = st.empty()   # holds the status box
pill_container = st.empty()     # animated 3-dot pill
progress_container = st.empty() # holds st.progress

run_clicked = st.button("🔎 Review Code", use_container_width=True)

st.markdown('</div>', unsafe_allow_html=True)  # card-inner
st.markdown('</div>', unsafe_allow_html=True)  # card
st.markdown('</div>', unsafe_allow_html=True)  # hero

# ===================== Helpers & core logic =====================
PY_EXE = sys.executable or "python"

def detect_language(src: str, name: Optional[str]) -> str:
    if language != "Auto":
        return language
    if name and name.lower().endswith(".py"):
        return "Python"
    if any(tok in src for tok in ("import ", "def ", "class ", "from ", "print(")):
        return "Python"
    return "JavaScript / Other"

def table_from_records(records: List[Dict], title: str):
    if not records:
        st.success(f"✅ No {title.lower()} found.")
        return
    st.subheader(title)
    st.table(records)

def _safe_env_for_subprocess() -> Dict[str, str]:
    return {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PATH": os.environ.get("PATH", "")}

# ---------- Compile check ----------
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

# ---------- Runtime probe ----------
TRACE_RE = re.compile(
    r'^\s*File "(?P<file>.+?)", line (?P<line>\d+),.*?\n(?P<code>[^\n]*?)\n(?P<etype>[A-Za-z_][\w\.]*)(?:: (?P<emsg>.*))?$',
    re.S | re.M
)
WARN_RE = re.compile(r'^(?P<file>.+?):(?P<line>\d+): (?P<category>\w+Warning): (?P<message>.+)$', re.M)

def run_runtime_probe(src: str, capture_warnings: bool = True, timeout: float = 3.0) -> Tuple[str, str, int, str]:
    tmpdir = tempfile.mkdtemp(prefix="revu_")
    script_path = os.path.join(tmpdir, "snippet.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(src)
    try:
        cmd = [PY_EXE, "-I", "-X", "dev"]
        if capture_warnings:
            cmd += ["-W", "default"]
        cmd += [script_path]
        completed = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env=_safe_env_for_subprocess(), cwd=tmpdir
        )
        return completed.stdout, completed.stderr, completed.returncode, tmpdir
    finally:
        try:
            for fn in os.listdir(tmpdir):
                try: os.remove(os.path.join(tmpdir, fn))
                except Exception: pass
            os.rmdir(tmpdir)
        except Exception:
            pass

def parse_first_exception(stderr: str) -> Optional[Dict]:
    matches = list(TRACE_RE.finditer(stderr))
    if matches:
        m = matches[-1]
        return {
            "Rule": (m.group("etype") or "").strip(),
            "Message": (m.group("emsg") or "").strip(),
            "Line": int(m.group("line")),
            "File": m.group("file")
        }
    lines = [ln for ln in stderr.strip().splitlines() if ln.strip()]
    if lines:
        last = lines[-1]
        if ":" in last:
            etype, emsg = last.split(":", 1)
            return {"Rule": etype.strip(), "Message": emsg.strip(), "Line": None, "File": "<user_code>"}
        return {"Rule": lines[-1].strip(), "Message": "", "Line": None, "File": "<user_code>"}
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

# ---------- Static scans ----------
SECURITY_PATTERNS = [
    (r'\beval\s*\(', "Use of eval()", "High"),
    (r'\bexec\s*\(', "Use of exec()", "High"),
    (r'\bpickle\.loads\s*\(', "Untrusted pickle deserialization", "High"),
    (r'\byaml\.load\s*\(', "yaml.load without SafeLoader", "High"),
    (r'\bsubprocess\.[A-Za-z_]+\s*\(.*shell\s*=\s*True', "subprocess with shell=True", "High"),
    (r'["\']?(password|secret|token|apikey|api_key|bearer)["\']?\s*[:=]\s*["\'][^"\']+["\']', "Possible hardcoded secret", "High"),
    (r'\brequests\.(get|post|put|delete|patch|head)\s*\(', "HTTP call without timeout", "Medium"),
    (r'\burllib\.request\.(urlopen|Request)\s*\(', "urllib request without timeout/verify", "Medium"),
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
MAINTAINABILITY_PATTERNS = [
    (r'def\s+\w+\s*\([^)]*(\w+\s*=\s*\[\]|\w+\s*=\s*\{\})[^)]*\)', "Mutable default argument", "Medium"),
    (r'^\s*print\s*\(.*\)\s*$', "Debug print call (consider logging)", "Low"),
    (r'^\s*from\s+\S+\s+import\s+\*\s*$', "Wildcard import", "Low"),
]
def run_static_scans(src: str) -> List[Dict]:
    findings = []
    def add(rule, msg, sev, line):
        findings.append({"Rule": rule, "Message": msg, "Severity": sev, "Line": line, "File": "<user_code>"})
    for pat, msg, sev in SECURITY_PATTERNS:
        for m in re.finditer(pat, src, flags=re.I):
            add("Security", msg, sev, src.count("\n", 0, m.start()) + 1)
    for pat, msg, sev in ERROR_HANDLING_PATTERNS:
        for m in re.finditer(pat, src):
            add("ErrorHandling", msg, sev, src.count("\n", 0, m.start()) + 1)
    for pat, msg, sev in ASYNC_SMELLS:
        for m in re.finditer(pat, src):
            add("Async", msg, sev, src.count("\n", 0, m.start()) + 1)
    for pat, msg, sev in MAINTAINABILITY_PATTERNS:
        for m in re.finditer(pat, src, flags=re.M):
            add("Maintainability", msg, sev, src.count("\n", 0, m.start()) + 1)
    for m in re.finditer(r'except\s+Exception\s*:\s*(?:pass|return\s+None\b)', src):
        add("ErrorHandling", "Broad except without handling", "Medium", src.count("\n", 0, m.start()) + 1)
    for m in re.finditer(r'\bsubprocess\.(run|call|Popen)\s*\(', src):
        seg = src[m.end(): m.end()+200]
        if "check=" not in seg and "Popen" not in m.group(1):
            add("Reliability", "subprocess.run without check=True (may ignore failures)", "Low", src.count("\n", 0, m.start()) + 1)
    return findings

# ---------- Ruff ----------
def run_ruff_on_code(src: str) -> List[Dict]:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8") as f:
        f.write(src); tmp_path = f.name
    try:
        completed = subprocess.run(["ruff", "check", "--output-format=json", tmp_path],
                                   capture_output=True, text=True)
        if completed.returncode not in (0, 1):
            raise FileNotFoundError(completed.stderr.strip() or "ruff invocation failed.")
        output = completed.stdout.strip()
        return [] if not output else json.loads(output)
    finally:
        try: os.remove(tmp_path)
        except OSError: pass

def show_ruff_results(results: List[Dict]):
    if not results:
        st.success("✅ No Ruff issues found."); return
    st.subheader("Ruff findings (Python)")
    counts = {}
    for r in results:
        code = r.get("code")
        if code: counts[code] = counts.get(code, 0) + 1
    if counts:
        st.caption("Counts by rule:")
        st.write({k: v for k, v in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)})
    rows = []
    for r in results:
        loc = r.get("location", {})
        rows.append({"Rule": r.get("code"), "Message": r.get("message"),
                     "Line": loc.get("row"), "Column": loc.get("column"), "File": r.get("filename")})
    st.table(rows)

# ---------- AI suggestions ----------
AI_CHECKLIST = r"""
You are a senior code reviewer. Give precise, actionable feedback...
"""
def _ai_review_once(client: OpenAI, prompt_code: str, language_hint: str) -> str:
    user_msg = f"Language: {language_hint}\n\nCode to review:\n\n{prompt_code}"
    resp = client.responses.create(model="gpt-4o-mini",
        input=[{"role": "system", "content": AI_CHECKLIST},{"role": "user", "content": user_msg}],)
    return resp.output_text.strip()

@st.cache_data(ttl=120)
def cached_ai_review(prompt_code: str, language_hint: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY", None)
    if not api_key:
        return "No OPENAI_API_KEY found. Add it via App ▸ Settings ▸ Advanced ▸ Secrets."
    os.environ["OPENAI_API_KEY"] = api_key
    client = OpenAI()
    for attempt in range(6):
        try:
            return _ai_review_once(client, prompt_code, language_hint)
        except RateLimitError:
            time.sleep((2 ** attempt) + random.random())
        except APIError:
            time.sleep(2)
        except Exception as e:
            return f"AI review error: {e}"
    return "AI is busy (rate limited). Please try again shortly."

def _export_button(all_findings: Dict[str, List[Dict]]):
    try:
        payload = json.dumps(all_findings, ensure_ascii=False, indent=2)
        st.download_button("⬇️ Download findings (JSON)", data=payload,
                           file_name="revu_findings.json", mime="application/json")
    except Exception:
        pass

# ---------- Animated progress helpers ----------
def start_progress():
    """Create status box, animated pill, and progress bar."""
    pill_container.markdown(
        '<div class="ai-pill"><span class="ai-dot"></span><span class="ai-dot"></span>'
        '<span class="ai-dot"></span><span style="margin-left:6px">Analyzing…</span></div>',
        unsafe_allow_html=True
    )
    try:
        # st.status provides an animated status container with steps (Streamlit ≥1.25)
        status = status_container.status("Analyzing your code…", state="running", expanded=True)
    except Exception:
        status = None
    bar = progress_container.progress(0)
    return status, bar

def step(progress_bar, status_box, pct: int, msg: str):
    progress_bar.progress(min(max(pct, 0), 100))
    if status_box:
        status_box.update(label=msg, state="running")

def finish_progress(progress_bar, status_box, ok: bool = True):
    progress_bar.progress(100)
    pill_container.empty()
    if status_box:
        status_box.update(label="Analysis complete." if ok else "Analysis finished with issues.", state="complete" if ok else "error")
    time.sleep(0.25)
    progress_container.empty()
    status_container.empty()

# ===================== Run review =====================
if run_clicked:
    if not code or not code.strip():
        st.warning("Please paste code or upload a file first.")
        st.stop()

    # Kick off animated progress UI
    status_box, pbar = start_progress()
    try:
        lang = detect_language(code, filename)
        all_findings: Dict[str, List[Dict]] = {"compile": [], "runtime": [], "warnings": [], "ruff": [], "security": []}

        if lang != "Python":
            step(pbar, status_box, 10, "Non-Python detected — limited static checks.")
            st.info("Non-Python detected. Static checks are limited; enable AI suggestions for deeper review.")
            finish_progress(pbar, status_box, ok=True)
        else:
            # 1) Compile-time
            step(pbar, status_box, 15, "Compile check…")
            comp = compile_check(code)
            all_findings["compile"] = comp
            table_from_records(comp, "Compile-time Errors")
            has_blockers = any(r["Rule"] in ("SyntaxError", "IndentationError", "TabError") for r in comp)

            # 2) Runtime (optional)
            if run_runtime and not has_blockers:
                step(pbar, status_box, 45, "Sandboxed runtime probe…")
                try:
                    out, err, rc, _tmp = run_runtime_probe(code, capture_warnings=show_warnings, timeout=3.5)
                    first_exc = parse_first_exception(err)
                    if first_exc:
                        all_findings["runtime"].append(first_exc)
                        table_from_records([first_exc], "Runtime Exception (first raised)")
                    else:
                        st.success("✅ No exception raised in short probe.")
                    if show_warnings:
                        warns = parse_warnings(err)
                        all_findings["warnings"] = warns
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
            else:
                step(pbar, status_box, 35, "Skipping runtime probe (blocked or disabled)…")

            # 3) Ruff
            step(pbar, status_box, 65, "Running Ruff linter…")
            try:
                ruff_results = run_ruff_on_code(code)
                for r in ruff_results:
                    loc = r.get("location", {})
                    all_findings["ruff"].append({
                        "Rule": r.get("code"),
                        "Message": r.get("message"),
                        "Line": loc.get("row"),
                        "Column": loc.get("column"),
                        "File": r.get("filename")
                    })
                show_ruff_results(ruff_results)
            except FileNotFoundError:
                st.error("Ruff not installed. Ensure `ruff==0.6.9` is in requirements.txt.")
            except Exception as e:
                st.error(f"Ruff error: {e}")

            # 4) Security scan
            step(pbar, status_box, 85, "Security & error-handling scan…")
            sec = run_static_scans(code)
            all_findings["security"] = sec
            if sec:
                st.subheader("Security & Error-handling Findings")
                st.table(sec)
            else:
                st.success("✅ No security/error-handling smells detected by heuristics.")

            # 5) AI review (optional)
            if use_ai:
                step(pbar, status_box, 92, "AI suggestions…")
                with st.spinner("Generating AI suggestions…"):
                    feedback = cached_ai_review(code, lang)
                st.subheader("💡 AI Suggestions")
                st.write(feedback)
            else:
                st.caption("Toggle AI suggestions in the sidebar for a deeper review.")

            # Export
            _export_button(all_findings)
            finish_progress(pbar, status_box, ok=True)
    except Exception:
        finish_progress(pbar, status_box, ok=False)
        raise

# ===================== Footer =====================
st.markdown('<div style="height: 24px;"></div>', unsafe_allow_html=True)

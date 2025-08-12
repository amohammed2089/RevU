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

# ===================== Minimal, clean UI (no scroll, soft glass) =====================
CSS = """
<style>
html, body, [data-testid="stAppViewContainer"] {
  height: 100%;
  margin: 0 !important;
  padding: 0 !important;
  overflow: hidden !important; /* no right scroll */
  background: linear-gradient(180deg, #0f172a 0%, #111827 60%, #0b1220 100%);
}
#MainMenu, header[data-testid="stHeader"], footer, [data-testid="stToolbar"] { display: none !important; }

[data-testid="stAppViewContainer"] > .main, .block-container {
  padding: 0 !important;
  margin: 0 auto !important;
  max-width: 1200px !important;
  min-height: 100vh !important;
  display: flex; flex-direction: column; justify-content: center;
}

/* Title */
.ai-title {
  font-size: clamp(28px, 4vw, 40px);
  font-weight: 800; letter-spacing:.2px;
  background: linear-gradient(90deg, #ffffff, #d1e9ff 60%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}

/* Two-card hero layout */
.hero {
  display: grid; grid-template-columns: 0.9fr 1.1fr; gap: 24px;
  width: 100%; height: min(84vh, 760px);
  padding: 10px 20px; box-sizing: border-box;
}

/* Glass cards */
.card {
  height: 100%; border-radius: 16px;
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.12);
  backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
  box-shadow: 0 12px 28px rgba(0,0,0,.35);
  overflow: hidden;
}
.card-inner { height: 100%; padding: 16px 16px 12px; display:flex; flex-direction:column; }

/* Robot image */
.bot-wrap { flex:1; display:flex; align-items:center; justify-content:center; }
.right-card .stTextArea textarea {
  height: 44vh !important; min-height: 240px !important; resize: none !important; border-radius: 12px !important;
}
.right-card [data-testid="stFileUploader"] section[aria-label="base"] { border-radius: 12px !important; }

/* Button */
.stButton > button {
  background: #e74c3c !important; color: #fff !important; border: 0 !important;
  border-radius: 12px !important; font-weight: 700 !important; padding: .9rem 1.2rem !important;
}
.stButton > button:hover { filter: brightness(.96); }

/* Text colors */
h1, h2, h3, p, span, label, div { color: #e5e7eb; }
.small-muted { color:#cbd5e1; font-size:.96rem; }

/* Subtle analyzing pill */
.ai-pill {
  display:inline-flex; align-items:center; gap:6px; padding:6px 10px; border-radius:999px;
  background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.14);
  font-size:.92rem; color:#e5e7eb;
}
.ai-dot { width:6px; height:6px; border-radius:50%; background:#cfe8ff; opacity:.7; animation: dot 1.2s infinite ease-in-out; }
.ai-dot:nth-child(2){ animation-delay: .2s; } .ai-dot:nth-child(3){ animation-delay: .4s; }
@keyframes dot { 0%,80%,100%{transform:scale(1); opacity:.5} 40%{transform:scale(1.6); opacity:1} }

/* Thin progress line */
.progress-wrap { width:100%; height:4px; background:rgba(255,255,255,.1); border-radius:999px; overflow:hidden; }
.progress-bar { height:100%; width:0%; background:#60a5fa; transition: width .25s ease; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ===================== Header =====================
st.markdown(
    '<div style="padding: 10px 20px 0;">'
    '<div class="ai-title">RevU — Your AI Code Reviewer</div>'
    '<p class="small-muted" style="margin:.25rem 0 0;">Paste code or upload a file. '
    'RevU catches compile errors, runtime exceptions, warnings, security smells, and Ruff issues.</p>'
    '</div>',
    unsafe_allow_html=True
)

# ===================== Hero =====================
st.markdown('<div class="hero">', unsafe_allow_html=True)

# Left: visual
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
st.markdown('</div></div></div>', unsafe_allow_html=True)

# Right: controls
st.markdown('<div class="card right-card"><div class="card-inner">', unsafe_allow_html=True)

with st.sidebar:
    st.header("Settings")
    language = st.selectbox("Language", ["Auto", "Python", "JavaScript / Other"], index=0)
    run_runtime = st.toggle("Run runtime checks (sandboxed subprocess)", value=False,
                            help="Executes code in an isolated Python subprocess with -I and -X dev.")
    show_warnings = st.toggle("Report warnings", value=True)
    use_ai = st.toggle("AI suggestions (requires OPENAI_API_KEY)", value=False)
    st.markdown("<p class='small-muted'>Flow: compile → (optional) runtime → Ruff → security → (optional) AI.</p>", unsafe_allow_html=True)

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

# Status area (subtle)
pill = st.empty()
progress_html = st.empty()   # custom thin bar
status_text = st.empty()     # step text

run_clicked = st.button("🔎 Review Code", use_container_width=True)

st.markdown('</div></div>', unsafe_allow_html=True)  # close right card
st.markdown('</div>', unsafe_allow_html=True)        # close hero

# ===================== Core (same functionality) =====================
PY_EXE = sys.executable or "python"

def detect_language(src: str, name: Optional[str]) -> str:
    if language != "Auto":
        return language
    if name and name.lower().endswith(".py"): return "Python"
    if any(tok in src for tok in ("import ", "def ", "class ", "from ", "print(")): return "Python"
    return "JavaScript / Other"

def table_from_records(records: List[Dict], title: str):
    if not records:
        st.success(f"✅ No {title.lower()} found."); return
    st.subheader(title); st.table(records)

def _safe_env_for_subprocess() -> Dict[str, str]:
    return {"PYTHONIOENCODING":"utf-8","PYTHONUTF8":"1","PATH":os.environ.get("PATH","")}

def compile_check(src: str) -> List[Dict]:
    try:
        compile(src, "<user_code>", "exec"); return []
    except Exception as e:
        return [{"Rule":type(e).__name__,"Message":str(e),"Line":getattr(e,"lineno",None),
                 "Column":getattr(e,"offset",None),"File":"<user_code>"}]

TRACE_RE = re.compile(
    r'^\s*File "(?P<file>.+?)", line (?P<line>\d+),.*?\n(?P<code>[^\n]*?)\n(?P<etype>[A-Za-z_][\w\.]*)(?:: (?P<emsg>.*))?$',
    re.S | re.M
)
WARN_RE = re.compile(r'^(?P<file>.+?):(?P<line>\d+): (?P<category>\w+Warning): (?P<message>.+)$', re.M)

def run_runtime_probe(src: str, capture_warnings: bool=True, timeout: float=3.0) -> Tuple[str,str,int,str]:
    tmpdir = tempfile.mkdtemp(prefix="revu_")
    path = os.path.join(tmpdir, "snippet.py")
    with open(path, "w", encoding="utf-8") as f: f.write(src)
    try:
        cmd = [PY_EXE,"-I","-X","dev"]; 
        if capture_warnings: cmd += ["-W","default"]
        cmd += [path]
        c = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env=_safe_env_for_subprocess(), cwd=tmpdir)
        return c.stdout, c.stderr, c.returncode, tmpdir
    finally:
        try:
            for fn in os.listdir(tmpdir):
                try: os.remove(os.path.join(tmpdir, fn))
                except Exception: pass
            os.rmdir(tmpdir)
        except Exception: pass

def parse_first_exception(stderr: str) -> Optional[Dict]:
    m = list(TRACE_RE.finditer(stderr))
    if m:
        g = m[-1]
        return {"Rule":(g.group("etype") or "").strip(),"Message":(g.group("emsg") or "").strip(),
                "Line":int(g.group("line")), "File":g.group("file")}
    lines = [ln for ln in stderr.strip().splitlines() if ln.strip()]
    if lines:
        last = lines[-1]
        if ":" in last:
            etype, emsg = last.split(":",1)
            return {"Rule":etype.strip(),"Message":emsg.strip(),"Line":None,"File":"<user_code>"}
        return {"Rule":lines[-1].strip(),"Message":"","Line":None,"File":"<user_code>"}
    return None

def parse_warnings(stderr: str) -> List[Dict]:
    return [{"Category":m.group("category"),"Message":m.group("message"),
             "Line":int(m.group("line")),"File":m.group("file")} for m in WARN_RE.finditer(stderr)]

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
    findings=[]
    def add(rule,msg,sev,line): findings.append({"Rule":rule,"Message":msg,"Severity":sev,"Line":line,"File":"<user_code>"})
    for pat,msg,sev in SECURITY_PATTERNS:
        for m in re.finditer(pat, src, flags=re.I): add("Security",msg,sev, src.count("\n",0,m.start())+1)
    for pat,msg,sev in ERROR_HANDLING_PATTERNS:
        for m in re.finditer(pat, src): add("ErrorHandling",msg,sev, src.count("\n",0,m.start())+1)
    for pat,msg,sev in ASYNC_SMELLS:
        for m in re.finditer(pat, src): add("Async",msg,sev, src.count("\n",0,m.start())+1)
    for pat,msg,sev in MAINTAINABILITY_PATTERNS:
        for m in re.finditer(pat, src, flags=re.M): add("Maintainability",msg,sev, src.count("\n",0,m.start())+1)
    for m in re.finditer(r'except\s+Exception\s*:\s*(?:pass|return\s+None\b)', src):
        add("ErrorHandling","Broad except without handling","Medium", src.count("\n",0,m.start())+1)
    for m in re.finditer(r'\bsubprocess\.(run|call|Popen)\s*\(', src):
        seg = src[m.end(): m.end()+200]
        if "check=" not in seg and "Popen" not in m.group(1):
            add("Reliability","subprocess.run without check=True (may ignore failures)","Low", src.count("\n",0,m.start())+1)
    return findings

def run_ruff_on_code(src: str) -> List[Dict]:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8") as f:
        f.write(src); tmp = f.name
    try:
        c = subprocess.run(["ruff","check","--output-format=json", tmp], capture_output=True, text=True)
        if c.returncode not in (0,1): raise FileNotFoundError(c.stderr.strip() or "ruff invocation failed.")
        return [] if not c.stdout.strip() else json.loads(c.stdout)
    finally:
        try: os.remove(tmp)
        except OSError: pass

def show_ruff_results(results: List[Dict]):
    if not results: st.success("✅ No Ruff issues found."); return
    st.subheader("Ruff findings (Python)")
    counts={}
    for r in results:
        code=r.get("code"); 
        if code: counts[code]=counts.get(code,0)+1
    if counts:
        st.caption("Counts by rule:"); st.write({k:v for k,v in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)})
    rows=[]
    for r in results:
        loc=r.get("location",{})
        rows.append({"Rule":r.get("code"),"Message":r.get("message"),"Line":loc.get("row"),
                     "Column":loc.get("column"),"File":r.get("filename")})
    st.table(rows)

AI_CHECKLIST = r"""You are a senior code reviewer. Give precise, actionable feedback..."""
def _ai_review_once(client: OpenAI, code_txt: str, language_hint: str) -> str:
    resp = client.responses.create(model="gpt-4o-mini",
        input=[{"role":"system","content":AI_CHECKLIST},
               {"role":"user","content":f"Language: {language_hint}\n\nCode to review:\n\n{code_txt}"}])
    return resp.output_text.strip()

@st.cache_data(ttl=120)
def cached_ai_review(code_txt: str, language_hint: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY", None)
    if not api_key: return "No OPENAI_API_KEY found. Add it via App ▸ Settings ▸ Advanced ▸ Secrets."
    os.environ["OPENAI_API_KEY"] = api_key
    client = OpenAI()
    for attempt in range(6):
        try: return _ai_review_once(client, code_txt, language_hint)
        except RateLimitError: time.sleep((2**attempt)+random.random())
        except APIError: time.sleep(2)
        except Exception as e: return f"AI review error: {e}"
    return "AI is busy (rate limited). Please try again shortly."

def _export_button(all_findings: Dict[str, List[Dict]]):
    try:
        payload = json.dumps(all_findings, ensure_ascii=False, indent=2)
        st.download_button("⬇️ Download findings (JSON)", data=payload, file_name="revu_findings.json", mime="application/json")
    except Exception:
        pass

# ---------- Subtle analyzing UI ----------
def show_pill(on: bool, text: str="Analyzing…"):
    if on:
        pill.markdown(f'<div class="ai-pill"><span class="ai-dot"></span><span class="ai-dot"></span>'
                      f'<span class="ai-dot"></span><span style="margin-left:6px">{text}</span></div>',
                      unsafe_allow_html=True)
    else:
        pill.empty()

def set_progress(pct: int):
    pct = max(0, min(100, pct))
    progress_html.markdown(f'<div class="progress-wrap"><div class="progress-bar" style="width:{pct}%;"></div></div>',
                           unsafe_allow_html=True)

# ===================== Run review =====================
if run_clicked:
    if not code or not code.strip():
        st.warning("Please paste code or upload a file first.")
        st.stop()

    show_pill(True, "Analyzing…")
    set_progress(5)
    status_text.caption("Detecting language…")

    lang = detect_language(code, filename)
    all_findings: Dict[str, List[Dict]] = {"compile": [], "runtime": [], "warnings": [], "ruff": [], "security": []}

    if lang != "Python":
        set_progress(15)
        status_text.caption("Non-Python detected — limited static checks. Enable AI suggestions for deeper review.")
        st.info("Non-Python detected. Static checks are limited; enable AI suggestions for deeper review.")
        show_pill(False)
        set_progress(100)
    else:
        # Compile
        set_progress(20); status_text.caption("Compile check…")
        comp = compile_check(code); all_findings["compile"] = comp
        table_from_records(comp, "Compile-time Errors")
        blockers = any(r["Rule"] in ("SyntaxError","IndentationError","TabError") for r in comp)

        # Runtime (optional)
        if run_runtime and not blockers:
            set_progress(45); status_text.caption("Sandboxed runtime probe…")
            try:
                out, err, rc, _tmp = run_runtime_probe(code, capture_warnings=show_warnings, timeout=3.5)
                m = parse_first_exception(err)
                if m: all_findings["runtime"].append(m); table_from_records([m], "Runtime Exception (first raised)")
                else: st.success("✅ No exception raised in short probe.")
                if show_warnings:
                    warns = parse_warnings(err); all_findings["warnings"]=warns; table_from_records(warns, "Warnings")
                if out.strip():
                    with st.expander("Program stdout"): st.code(out)
                if err.strip():
                    with st.expander("Program stderr / traceback"): st.code(err)
            except subprocess.TimeoutExpired:
                st.warning("Runtime probe timed out (code may block or run too long).")
            except Exception as e:
                st.error(f"Runtime probe error: {e}")
        else:
            set_progress(35); status_text.caption("Skipping runtime probe (disabled or blocked by syntax).")

        # Ruff
        set_progress(65); status_text.caption("Running Ruff linter…")
        try:
            ruff_results = run_ruff_on_code(code)
            for r in ruff_results:
                loc = r.get("location", {})
                all_findings["ruff"].append({"Rule":r.get("code"),"Message":r.get("message"),
                                             "Line":loc.get("row"),"Column":loc.get("column"),"File":r.get("filename")})
            show_ruff_results(ruff_results)
        except FileNotFoundError:
            st.error("Ruff not installed. Ensure `ruff==0.6.9` is in requirements.txt.")
        except Exception as e:
            st.error(f"Ruff error: {e}")

        # Security / handling
        set_progress(85); status_text.caption("Security & error-handling scan…")
        sec = run_static_scans(code); all_findings["security"]=sec
        if sec: st.subheader("Security & Error-handling Findings"); st.table(sec)
        else: st.success("✅ No security/error-handling smells detected by heuristics.")

        # AI (optional)
        if use_ai:
            set_progress(92); status_text.caption("AI suggestions…")
            with st.spinner("Generating AI suggestions…"):
                fb = cached_ai_review(code, lang)
            st.subheader("💡 AI Suggestions"); st.write(fb)
        else:
            st.caption("Toggle AI suggestions in the sidebar for a deeper review.")

        _export_button(all_findings)
        set_progress(100); show_pill(False); status_text.caption("Analysis complete.")

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
    # load robot image from repo root if present
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

# -------------------- AI review (resilient) --------------------
def _ai_review_once(client: OpenAI, prompt_code: str, language_hint: str) -> str:
    checklist = """
You are a senior code reviewer. Give precise, actionable feedback with short code snippets.
Check EVERYTHING from very minor to very critical issues. Use these headings with severity labels:
[Critical/High/Medium/Low] Syntax & parsing
[Critical/High/Medium/Low] Runtime errors & exceptions
[Critical/High/Medium/Low] Logic & algorithmic correctness
[Critical/High/Medium/Low] Security (injections, path traversal, secrets, deserialization, authN/Z)
[Critical/High/Medium/Low] Performance & complexity
[Critical/High/Medium/Low] Concurrency/async pitfalls
[Critical/High/Medium/Low] Resource handling (files, sockets, memory)
[Critical/High/Medium/Low] Input validation & edge cases
[Critical/High/Medium/Low] Error handling & resilience
[Critical/High/Medium/Low] API usage & compatibility
[Critical/High/Medium/Low] Maintainability & readability
[Critical/High/Medium/Low] Style/formatting
[Critical/High/Medium/Low] Testing & coverage
[Critical/High/Medium/Low] Dependency & config risks
[Critical/High/Medium/Low] Web-specific headers/CORS/auth when relevant
Rules: Group findings under these headings and include concrete fixes (small code blocks or diff-style).
"""
    user_msg = f"Language: {language_hint}\n\nCode to review:\n\n{prompt_code}"

    resp = client.responses.create(
        model="gpt-4o-mini",  # lighter model: better rate limits & costs
        input=[
            {"role": "system", "content": checklist},
            {"role": "user", "content": user_msg},
        ],
    )
    return resp.output_text.strip()

@st.cache_data(ttl=120)
def cached_ai_review(prompt_code: str, language_hint: str) -> str:
    """Wrapper that retries on rate limits/transient errors and caches results briefly."""
    api_key = os.environ.get("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY", None)
    if not api_key:
        return "No OPENAI_API_KEY found. Add it via App ▸ Settings ▸ Advanced ▸ Secrets."

    os.environ["OPENAI_API_KEY"] = api_key
    client = OpenAI()

    last_err = None
    for attempt in range(6):  # ~ up to ~63s worst case
        try:
            return _ai_review_once(client, prompt_code, language_hint)
        except RateLimitError as e:
            last_err = e
            time.sleep((2 ** attempt) + random.random())  # 1s, 2s, 4s, 8s, ...
            continue
        except APIError as e:
            last_err = e
            time.sleep(2)
            continue
        except Exception as e:
            return f"AI review error: {e}"
    return "AI is busy (rate limited). Please try again shortly."

# -------------------- Run review --------------------
if run_clicked:
    if not code or not code.strip():
        st.warning("Please paste code or upload a file first.")
        st.stop()

    # determine language (simple heuristic)
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
        st.write(feedback)
    else:
        st.caption("Toggle AI suggestions in the sidebar to get deep review.")

import os
import json
import subprocess
import tempfile
from typing import List, Dict

import streamlit as st
# OpenAI v1+ SDK (>=1.97.2)
from openai import OpenAI


# ---------- UI ----------
st.set_page_config(page_title="RevU — Web Code Review Bot", page_icon="🤖")
st.title("🤖 RevU — Web Code Review Bot")
st.write(
    "Paste code or upload a file. Get instant lint feedback (Python via Ruff) "
    "and optional AI suggestions using the latest OpenAI API."
)

with st.sidebar:
    st.header("Settings")
    language = st.selectbox("Language", ["Auto", "Python", "JavaScript / Other"], index=0)
    use_ai = st.toggle("AI suggestions (requires OPENAI_API_KEY secret)", value=False)
    st.caption("Tip: Ruff runs locally for Python. AI can review any language.")


# ---------- Helpers ----------
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
    # Show quick counts by rule
    counts = {}
    for r in results:
        code = r.get("code")
        if code:
            counts[code] = counts.get(code, 0) + 1
    if counts:
        st.write({k: v for k, v in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)})

    # Detailed table
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


def ai_review(prompt_code: str, language_hint: str) -> str:
    """
    Use OpenAI Responses API (SDK v1.x) to produce a FULL-SPECTRUM review:
    from tiny style issues to critical security risks.
    """
    # Read key from Streamlit Secrets or env; do NOT hardcode keys.
    api_key = os.environ.get("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY", None)
    if not api_key:
        return "No OPENAI_API_KEY found in Secrets. Add it in the app settings."

    # Make sure the SDK sees the key in env (OpenAI() reads from env)
    os.environ["OPENAI_API_KEY"] = api_key
    client = OpenAI()  # uses OPENAI_API_KEY from environment

    # Comprehensive checklist prompt (short but exhaustive)
    checklist = """
You are a senior code reviewer. Give precise, actionable feedback with short code snippets.
Check EVERYTHING, from very minor to critical issues. Use these categories:

1) Syntax & parsing errors
2) Runtime errors & exceptions
3) Logic/algorithmic correctness
4) Security vulnerabilities (e.g., injections, path traversal, secrets, unsafe deserialization)
5) Performance & complexity (inefficient loops/queries, N+1, large allocations)
6) Concurrency/threading/async pitfalls (deadlocks, races, blocking calls)
7) Resource handling (files, sockets, memory leaks)
8) Input validation & edge cases (bounds, null/None, types, user input)
9) Error handling & resilience (try/except, retries, fallbacks)
10) API usage & compatibility (deprecated, wrong params, unsafe defaults)
11) Maintainability & readability (naming, comments, duplication, long functions)
12) Style/formatting (PEP8, lint rules, consistent imports)
13) Testing & coverage suggestions
14) Dependency & config risks (outdated/vulnerable libs, hardcoded creds)
15) Security headers/CORS/authN/authZ if applicable (web/backend)

Rules:
- Be concise but complete; group findings under these headings.
- Mark each finding as: [Critical] [High] [Medium] or [Low].
- When possible, propose exact fixes (diff-style or small code blocks).
"""

    user_msg = f"Language: {language_hint}\n\nCode to review:\n\n{prompt_code}"

    resp = client.responses.create(
        model="gpt-4o",
        input=[
            {"role": "system", "content": checklist},
            {"role": "user", "content": user_msg},
        ],
    )

    return resp.output_text.strip()


# ---------- App body ----------
code = st.text_area("Paste your code here", height=220, placeholder="# Paste code or upload a file below…")
uploaded = st.file_uploader("…or upload a code file", type=None)
if uploaded and not code:
    try:
        code = uploaded.read().decode("utf-8", errors="ignore")
    except Exception:
        code = ""

if st.button("🔎 Review Code", type="primary", use_container_width=True):
    if not code.strip():
        st.warning("Please paste code or upload a file first.")
        st.stop()

    # Auto-detect language (simple heuristic)
    lang = language
    if lang == "Auto":
        if uploaded and uploaded.name.endswith(".py"):
            lang = "Python"
        elif any(tok in code for tok in ["import ", "def ", "class "]):
            lang = "Python"
        else:
            lang = "JavaScript / Other"

    # Run Ruff for Python
    if lang == "Python":
        st.info("Running Ruff (Python linter) locally…")
        try:
            ruff_results = run_ruff_on_code(code)
            show_ruff_results(ruff_results)
        except FileNotFoundError:
            st.error("Ruff not installed. Ensure `ruff` is listed in requirements.txt.")
        except Exception as e:
            st.error(f"Ruff error: {e}")
    else:
        st.caption("Skipping Ruff (Python-only).")

    # AI suggestions
    if use_ai:
        with st.spinner("Generating AI suggestions…"):
            feedback = ai_review(code, lang)
        st.subheader("💡 AI Suggestions (full-spectrum review)")
        st.write(feedback)
    else:
        st.caption("Enable AI suggestions in the sidebar for deep review (all categories).")

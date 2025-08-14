import streamlit as st
import tempfile, subprocess, json, os
from typing import List, Dict

st.set_page_config(page_title="Web Code Review Bot", page_icon="🤖")
st.title("🤖 Web Code Review Bot")
st.write("Paste code or upload a file. Get instant lint feedback (Python via Ruff) and optional AI suggestions.")

with st.sidebar:
    st.header("Settings")
    language = st.selectbox("Language", ["Auto", "Python", "JavaScript / Other"], index=0)
    use_ai = st.toggle("AI suggestions (requires OPENAI_API_KEY)", value=False)
    st.markdown("---")
    st.caption("Tip: For Python, Ruff runs locally. For other languages, AI suggestions can still provide feedback.")

code = st.text_area("Paste your code here", height=220, placeholder="# Paste code or upload a file below...")

uploaded = st.file_uploader("...or upload a code file", type=None)
if uploaded and not code:
    try:
        code = uploaded.read().decode("utf-8", errors="ignore")
    except Exception:
        code = ""

def run_ruff_on_code(src: str) -> List[Dict]:
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
        findings = json.loads(output)
        return findings
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

def show_ruff_results(results: List[Dict]):
    if not results:
        st.success("✅ No Ruff issues found.")
        return
    st.subheader("Ruff findings")
    from collections import Counter
    codes = Counter(r.get("code") for r in results if "code" in r)
    st.write({k: v for k, v in sorted(codes.items(), key=lambda kv: kv[1], reverse=True)})
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
    try:
        import pandas as pd
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
    except Exception:
        st.write(rows)

def ai_review(prompt_code: str, language_hint: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY", None)
    if not api_key:
        return "No OPENAI_API_KEY found. Add it in Streamlit secrets/settings."
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        system = "You are a senior code reviewer. Give precise, actionable suggestions."
        user = f"Review the following {language_hint} code:\n\n{prompt_code}"
        resp = client.responses.create(
            model="gpt-4o",
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
        return resp.output_text.strip()
    except Exception as e:
        return f"AI review error: {e}"

run = st.button("🔎 Review Code", type="primary", use_container_width=True)

if run:
    if not code.strip():
        st.warning("Please paste code or upload a file first.")
        st.stop()
    lang = language
    if lang == "Auto":
        if uploaded and uploaded.name.endswith(".py"):
            lang = "Python"
        elif "import " in code or "def " in code or "class " in code:
            lang = "Python"
        else:
            lang = "JavaScript / Other"
    if lang == "Python":
        st.info("Running Ruff (Python linter) locally...")
        try:
            ruff_results = run_ruff_on_code(code)
            show_ruff_results(ruff_results)
        except FileNotFoundError:
            st.error("Ruff is not installed. Please add `ruff` to requirements.txt.")
        except Exception as e:
            st.error(f"Ruff error: {e}")
    else:
        st.write("Skipping Ruff (Python-only).")
    if use_ai:
        with st.spinner("Generating AI suggestions..."):
            feedback = ai_review(code, lang)
        st.subheader("💡 AI Suggestions")
        st.write(feedback)
    else:
        st.caption("Enable AI suggestions in the sidebar to get extra ideas.")

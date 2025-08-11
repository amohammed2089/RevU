# RevU — Your AI Code Reviewer (Streamlit)

RevU reviews pasted or uploaded code and surfaces:
- **Compile-time errors** (`SyntaxError`, `IndentationError`, `TabError`, etc.)
- **Sandboxed runtime exceptions** (first raised exception) and **Warnings** (Deprecation/Resource/Encoding/…)
- **Security & error-handling smells** (e.g., `eval`, `pickle.loads`, `yaml.load` without `SafeLoader`, `shell=True`, bare/broad `except`)
- **Ruff** lint results (Python)
- Optional **AI suggestions** (OpenAI)

> Runtime execution is **off by default**. Enable it only for trusted snippets.

---

## Quick start

```bash
# 1) Clone
git clone <your-repo-url>
cd <your-repo-name>

# 2) (Optional) create venv
python -m venv .venv && . .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3) Install
pip install -r requirements.txt

# 4) Run
streamlit run app.py

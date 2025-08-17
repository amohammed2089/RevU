# RevU — Enhanced Python Code Reviewer

RevU is a Streamlit app that analyzes code across:
- **Syntax/Indentation** (built-in `ast.parse`)
- **Style/Lint** (Ruff)
- **Types** (mypy)
- **Security** (Bandit)
- **Formatting** (Black)
- **Import Order** (isort)
- **Docstrings** (pydocstyle)
- **Optional runtime smoke test** (subprocess; off by default)

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py

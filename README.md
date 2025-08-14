# Web Code Review Bot (Streamlit)

A shareable web app where anyone can paste or upload code to get instant feedback:
- **Python linting** locally via **Ruff**
- **Optional AI suggestions** via OpenAI (set `OPENAI_API_KEY` in secrets)

## Deploy on Streamlit Community Cloud
1. Push these files to a GitHub repo.
2. On Streamlit Cloud, create a new app from that repo, select `app.py`.
3. (Optional) Add `OPENAI_API_KEY` in Secrets for AI suggestions.
4. Share your public URL.

## Local run
pip install -r requirements.txt  
streamlit run app.py

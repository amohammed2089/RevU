# RevU — Web Code Review Bot

Paste or upload code and get instant feedback:
- **Python linting** via Ruff
- **Optional AI suggestions** via OpenAI (set `OPENAI_API_KEY` in Secrets)

## Deploy on Streamlit Community Cloud
1) Put `app.py` and `requirements.txt` in a GitHub repo.
2) In Streamlit Cloud, create a new app from that repo (entry file: `app.py`).
3) (Optional) Add `OPENAI_API_KEY` in **Secrets** to enable AI suggestions.
4) Share your public URL.

Docs:
- Streamlit Deploy: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app  
- Secrets: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management  
- Ruff Linter: https://docs.astral.sh/ruff/  
- OpenAI Responses API: https://platform.openai.com/docs/api-reference/responses

## Local run

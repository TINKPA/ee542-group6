# Group Chat Web App + LLM Bot

> Lab 9 notes: the instructor's zip shipped without `backend/`; `backend/app.py` and
> `backend/requirements.txt` here are ours. With `RAG_API_BASE` set in `.env`, "?" questions go to
> the F-1 knowledge base (`../rag/rag_api.py`) instead of the bare LLM. See `../../README.md`.

FastAPI + MySQL + vanilla HTML/JS group chat with LLM bot (OpenAI-compatible server such as self-hosted Llama 3 via llama.cpp).

## Quick Start (Dev)

```bash
# 1) MySQL
# create DB & user, or run sql/schema.sql

# 2) Backend
cd backend
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# copy env and edit values
cp ../.env.example ../.env

# 3) Run app
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000

LLM endpoint defaults to http://localhost:8001/v1 (llama.cpp server). Set `LLM_API_BASE`, `LLM_MODEL`, `LLM_API_KEY` if needed in `.env`.

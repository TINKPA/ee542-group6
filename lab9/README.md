# Lab 9 — Custom Chatbot with an LLM and Embeddings: F-1 Compass

A group chat for USC international students whose bot answers F-1 / OPT / CPT
questions from official sources only (8 CFR 214.2(f), USCIS, SEVP, ICE, USC
OIS) and links every answer to the pages it used.

| Part | Code | What it does |
|---|---|---|
| 1 | [`code/groupchat/backend/app.py`](code/groupchat/backend/app.py), [`frontend/`](code/groupchat/frontend) | FastAPI + MySQL group chat (sign-up/login with bcrypt + JWT, REST + WebSocket broadcast). The instructor's zip has no `backend/`, so it is written here against `frontend/app.js`. A message with "?" asks the bot |
| 1 | [`code/groupchat/run_llm.sh`](code/groupchat/run_llm.sh) | Option A: llama.cpp `llama-server` with Llama 3.1 8B Instruct (Q4_K_M), OpenAI-compatible on :8001 |
| 2 | [`code/groupchat/twa_android_src/`](code/groupchat/twa_android_src) | Trusted Web Activity wrapper (template; not yet built) |
| 3 | [`code/rag/rag_core.py`](code/rag/rag_core.py) | Extract PDF / HTML / text into MySQL tables, `CharacterTextSplitter` (500 chars, overlap 100), OpenAI `text-embedding-3-small` into FAISS, `ConversationalRetrievalChain` + `ConversationBufferMemory` |
| 3 | [`code/rag/driver.py`](code/rag/driver.py) | Ingest a folder, then ask questions until `exit` |
| 3 | [`code/rag/web_app.py`](code/rag/web_app.py) | Streamlit site: sidebar upload of one or many files, chat, and the ranked context with each chunk's embedding |
| 4 | [`code/rag/f1/`](code/rag/f1) | `fetch_sources.py` collects 59 official F-1 sources into a manifest, `build_kb.py` builds the `f1` knowledge base, `eval_qa.py` checks 12 real questions + 1 off-topic one |
| 4 | [`code/rag/rag_api.py`](code/rag/rag_api.py) | `/ask` service (:8002) with the F-1 prompt and MMR retrieval; the chat backend calls it when `RAG_API_BASE` is set |
| 5 | [`code/rag/hist_embed.py`](code/rag/hist_embed.py) | Word2Vec (gensim) word vectors, our own numpy k-means, normalized K-bin word-cluster histogram per chunk, plus five switchable improvements |
| 5 | [`code/rag/eval_part5.py`](code/rag/eval_part5.py) | Retrieval benchmark: 200 generated questions per collection, R@k / MRR for OpenAI, BM25, mean Word2Vec and every histogram variant |

## Running it

```bash
# MySQL 8+ with the database and user
mysql -uroot < code/groupchat/sql/schema.sql

# LLM (Part 1): build llama.cpp, download a GGUF, then
code/groupchat/run_llm.sh

# chat app: backend venv, .env from .env.example (set JWT_SECRET), then
cd code/groupchat/backend && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
../run_app.sh                                   # http://localhost:8000

# RAG (Parts 3-5): OPENAI_API_KEY in the environment
cd code/rag && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python driver.py --docs <folder> --collection ads --show-context
./run_web.sh                                    # http://localhost:8501
.venv/bin/python f1/fetch_sources.py && .venv/bin/python f1/build_kb.py --hist
./run_api.sh                                    # then RAG_API_BASE=http://127.0.0.1:8002 in the chat .env
.venv/bin/python f1/eval_qa.py
.venv/bin/python eval_part5.py --collection f1 --sweep --final --clusters 8
```

## Results

**Part 4, answers** ([`data/raw/part4_eval_openai.log`](data/raw/part4_eval_openai.log)): 13/13 —
all 12 F-1 questions state the key facts (e.g. OPT filing window 90 days before / 60 days after,
150 days of unemployment on STEM OPT, 20 hours on campus) with the right agencies cited, and the
off-topic question is declined. Same 13/13 with the histogram embedding.

**Part 5, retrieval** — rank of the source chunk among all chunks, 200 questions:

| Method | ADS corpus R@5 | F-1 corpus R@5 |
|---|---|---|
| OpenAI text-embedding-3-small | 0.925 | 0.905 |
| BM25 | 0.895 | 0.645 |
| Histogram, handout baseline (N=100, K=200) | 0.405 | 0.225 |
| Histogram + stopwords + soft assignment + bin IDF + sqrt, K=800 | 0.780 | 0.500 |
| same, K=1600 | 0.805 | 0.555 |

Full tables: [`data/raw/part5_eval_ads.log`](data/raw/part5_eval_ads.log), [`data/raw/part5_eval_f1.log`](data/raw/part5_eval_f1.log).

## Data

`data/f1/manifest.json` lists every F-1 source (agency, URL, fetch time, sha256); the pages
themselves are not redistributed — `fetch_sources.py` downloads them again.
`data/part5/qa_*.json` are the generated benchmark questions.

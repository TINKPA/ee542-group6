#!/usr/bin/env bash
# EE542 Lab 9 Part 4: run the RAG API (knowledge base for the group chat bot) on :8002.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
exec .venv/bin/uvicorn rag_api:app --host 127.0.0.1 --port "${RAG_API_PORT:-8002}"

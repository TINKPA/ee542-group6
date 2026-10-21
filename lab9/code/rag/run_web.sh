#!/usr/bin/env bash
# EE542 Lab 9 Part 3: run the document-upload + chat website on :8501.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
exec .venv/bin/streamlit run web_app.py --server.port "${RAG_PORT:-8501}" --server.headless true \
  --browser.gatherUsageStats false

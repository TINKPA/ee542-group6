#!/usr/bin/env bash
# EE542 Lab 9 Part 1 (Option A): serve Llama 3.1 8B Instruct with llama.cpp's
# OpenAI-compatible server on :8001. Paths overridable via env.
#   LLAMA_DIR=~/Developer/llama.cpp MODEL=~/Developer/models/<file>.gguf ./run_llm.sh
set -euo pipefail
LLAMA_DIR="${LLAMA_DIR:-$HOME/Developer/llama.cpp}"
MODEL="${MODEL:-$HOME/Developer/models/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf}"
exec "$LLAMA_DIR/build/bin/llama-server" -m "$MODEL" --host 0.0.0.0 --port "${LLM_PORT:-8001}" \
  --ctx-size 4096 --alias "$(basename "$MODEL" .gguf)" ${LLM_API_KEY:+--api-key "$LLM_API_KEY"}

#!/usr/bin/env bash
# EE542 Lab 9 Part 1: run the FastAPI chat backend on :8000 (reads ../.env).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/backend"
. .venv/bin/activate
exec uvicorn app:app --host 0.0.0.0 --port "${APP_PORT:-8000}"

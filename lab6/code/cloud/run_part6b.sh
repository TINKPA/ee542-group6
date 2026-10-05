#!/usr/bin/env bash
# EE542 Lab 6 Part 6.2: sweep the standalone best-shape kernel, same N list and
# harness as Parts 2/4/6.1, so it is one more row in the Part 5 table.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v nvcc >/dev/null || export PATH="/usr/local/cuda/bin:$PATH"
SIZES=(${SIZES:-256 512 768 1024 1536 2048 3072})
echo "=== Part 6.2 best-shape sweep"
BIN="$here/../part6/matrix_best" "$here/../part2/sweep_gpu.sh" "${SIZES[@]}"
echo "DONE"

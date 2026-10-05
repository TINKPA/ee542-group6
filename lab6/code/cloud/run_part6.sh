#!/usr/bin/env bash
# EE542 Lab 6: cuBLAS sweep on the cloud GPU box, same N list as Parts 1-4.
#   nohup ./run_part6.sh > run6.log 2>&1 &
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v nvcc >/dev/null || export PATH="/usr/local/cuda/bin:$PATH"
SIZES=(${SIZES:-256 512 768 1024 1536 2048 3072})
echo "=== cuBLAS sweep"
BIN="$here/../part6/matrix_cublas" "$here/../part2/sweep_gpu.sh" "${SIZES[@]}"
echo "DONE"

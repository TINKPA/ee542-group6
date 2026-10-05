#!/usr/bin/env bash
# EE542 Lab 6: tiled-kernel sweep on the cloud GPU box, same N list as Parts 1-3.
#   nohup ./run_part4.sh > run4.log 2>&1 &
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v nvcc >/dev/null || export PATH="/usr/local/cuda/bin:$PATH"
SIZES=(${SIZES:-256 512 768 1024 1536 2048 3072})
echo "=== tiled GPU sweep (TILE_WIDTH 16)"
BIN="$here/../part4/matrix_tiled" "$here/../part2/sweep_gpu.sh" "${SIZES[@]}"
echo "DONE"

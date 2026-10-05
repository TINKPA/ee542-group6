#!/usr/bin/env bash
# Part 8 step: one GPU convolution sweep. ./run_part8_gpu.sh naive|tiled
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v nvcc >/dev/null || export PATH="/usr/local/cuda/bin:$PATH"
k="${1:-tiled}"
echo "=== Part 8 GPU sweep ($k)"; BIN="$here/../part8/conv_gpu" KARGS="--kernel $k" "$here/../part8/sweep_conv.sh"; echo "DONE"

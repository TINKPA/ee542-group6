#!/usr/bin/env bash
# Stability probe: alternate cublas 2048 and conv 2048/5x5 ROUNDS times with a
# pause, reading clocks/power/temperature in between. Appends to data/raw/probe_<host>.log.
#   ./gpu_probe.sh [ROUNDS] [label]
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v nvcc >/dev/null || export PATH="/usr/local/cuda/bin:$PATH"
rounds="${1:-5}"; label="${2:-probe}"
log="$here/../../data/raw/probe_$(hostname -s).log"; mkdir -p "$(dirname "$log")"
make -s -C "$here/../part6" matrix_cublas 2>&1 | grep -v warning || true
make -s -C "$here/../part8" conv_gpu 2>&1 | grep -v warning || true
{
echo "## $label $(date -u +%H:%M:%SZ)"
for i in $(seq 1 "$rounds"); do
  c="$("$here/../part6/matrix_cublas" 2048 | grep -o 'kernel_ms=[0-9.]* h2d_ms=[0-9.]* d2h_ms=[0-9.]*')"
  v="$("$here/../part8/conv_gpu" --kernel tiled --random 2048 5 | grep -o 'kernel_ms=[0-9.]* h2d_ms=[0-9.]*')"
  s="$(nvidia-smi --query-gpu=clocks.sm,power.draw,temperature.gpu,clocks_throttle_reasons.active --format=csv,noheader)"
  echo "round $i | cublas $c | conv5 $v | smi $s"
  sleep 4
done
} | tee -a "$log"

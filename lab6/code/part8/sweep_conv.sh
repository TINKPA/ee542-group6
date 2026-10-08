#!/usr/bin/env bash
# EE542 Lab 6 Part 8: time one convolution binary over an M x N grid on random
# inputs, REPEATS runs per cell, one CSV row per run. Paths relative to this script.
#
#   ./sweep_conv.sh                                   # conv_cpu, M 512..4096 x N 3..15
#   BIN=./conv_gpu KARGS="--kernel naive" ./sweep_conv.sh
#   MS="512 1024" NS="3 5" REPEATS=1 ./sweep_conv.sh  # a corner of the grid
#   OUT=... to name the CSV; appends if it exists (header written once).
# CSV columns: host,gpu,M,N,repeat,<keys of the binary's key=value line>
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPEATS="${REPEATS:-3}"
BIN="${BIN:-$here/conv_cpu}"
KARGS="${KARGS:-}"
MS=(${MS:-512 1024 2048 4096})
NS=(${NS:-3 5 7 11 15})
name="$(basename "$BIN")"; [ -n "$KARGS" ] && name="${name}_${KARGS##* }"   # conv_gpu_naive etc.
OUT="${OUT:-$here/../../data/raw/${name}_$(hostname -s).csv}"
make -s -C "$(dirname "$BIN")" "$(basename "$BIN")"
host="$(hostname -s)"
gpu="$( (nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo none) | head -1 | tr ' ' '_')"
mkdir -p "$(dirname "$OUT")"
for M in "${MS[@]}"; do
  for N in "${NS[@]}"; do
    for r in $(seq 1 "$REPEATS"); do
      line="$("$BIN" $KARGS --random "$M" "$N" | grep '^wall=')"
      keys="$(tr ' ' '\n' <<<"$line" | cut -d= -f1 | paste -sd, -)"
      vals="$(tr ' ' '\n' <<<"$line" | cut -d= -f2 | paste -sd, -)"
      [ -s "$OUT" ] || echo "host,gpu,M,N,repeat,$keys" > "$OUT"
      echo "$host,$gpu,$M,$N,$r,$vals" | tee -a "$OUT"
    done
  done
done
echo "wrote $OUT"

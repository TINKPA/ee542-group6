#!/usr/bin/env bash
# EE542 Lab 6 Part 2: run matrix_gpu for a list of N, several repeats each,
# one CSV row per run. Paths are relative to this script.
#
#   ./sweep_gpu.sh                      # N = 512 1024 2048, 3 repeats
#   ./sweep_gpu.sh 256 512 768 1024 1536 2048 3072
#   REPEATS=5 ./sweep_gpu.sh
#   BIN=../part4/matrix_tiled OUT=../../data/raw/tiled_x.csv ./sweep_gpu.sh
#
# The binary prints one "key=value key=value ..." line; its keys become the
# CSV columns, after host,gpu,N,repeat. Works for every GPU binary in this lab.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPEATS="${REPEATS:-3}"
BIN="${BIN:-$here/matrix_gpu}"
name="$(basename "$BIN")"
OUT="${OUT:-$here/../../data/raw/${name}_$(hostname -s).csv}"
sizes=("$@"); [ ${#sizes[@]} -eq 0 ] && sizes=(512 1024 2048)

make -s -C "$(dirname "$BIN")" "$name"
host="$(hostname -s)"
gpu="$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1 | tr ' ' '_')"
mkdir -p "$(dirname "$OUT")"

for N in "${sizes[@]}"; do
  for r in $(seq 1 "$REPEATS"); do
    line="$("$BIN" "$N" | grep '^wall=')"
    keys="$(tr ' ' '\n' <<<"$line" | cut -d= -f1 | paste -sd, -)"
    vals="$(tr ' ' '\n' <<<"$line" | cut -d= -f2 | paste -sd, -)"
    [ -s "$OUT" ] || echo "host,gpu,N,repeat,$keys" > "$OUT"
    echo "$host,$gpu,$N,$r,$vals" | tee -a "$OUT"
  done
done
echo "wrote $OUT"

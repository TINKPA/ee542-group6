#!/usr/bin/env bash
# EE542 Lab 6 Part 6.2: run the tile-shape search harness on the cloud GPU box.
# Output: data/raw/fast_<host>.csv (the harness's results_6_2.csv) + full stdout log.
#   nohup ./run_part62.sh > run62.log 2>&1 &
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v nvcc >/dev/null || export PATH="/usr/local/cuda/bin:$PATH"
SIZES=(${SIZES:-256 512 768 1024 1536 2048 3072 4096})
raw="$here/../../data/raw"; mkdir -p "$raw"
make -s -C "$here/../part6" matrix_fast
echo "=== Part 6.2 search: ${SIZES[*]}"
( cd "$here/../part6" && ./matrix_fast "${SIZES[@]}" | tee "$raw/fast_$(hostname -s).log" && mv results_6_2.csv "$raw/fast_$(hostname -s).csv" )
echo "DONE"

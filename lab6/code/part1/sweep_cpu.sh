#!/usr/bin/env bash
# EE542 Lab 6 Part 1: run matrix_cpu for a list of N, several repeats each,
# and append one CSV row per run. Paths are relative to this script.
#
#   ./sweep_cpu.sh                      # N = 512 1024 2048, 3 repeats
#   ./sweep_cpu.sh 256 512 1024         # custom N list
#   REPEATS=5 ./sweep_cpu.sh            # more repeats
#   OUT=../../data/raw/cpu_cloud.csv ./sweep_cpu.sh   # different output file
#
# CSV columns: host,machine,N,repeat,wall_s,cpu_s,checksum,gflops
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPEATS="${REPEATS:-3}"
OUT="${OUT:-$here/../../data/raw/cpu_$(hostname -s).csv}"
sizes=("$@"); [ ${#sizes[@]} -eq 0 ] && sizes=(512 1024 2048)

make -s -C "$here" matrix_cpu
machine="$(uname -m)"
host="$(hostname -s)"
mkdir -p "$(dirname "$OUT")"
[ -s "$OUT" ] || echo "host,machine,N,repeat,wall_s,cpu_s,checksum,gflops" > "$OUT"

for N in "${sizes[@]}"; do
  for r in $(seq 1 "$REPEATS"); do
    line="$("$here/matrix_cpu" "$N" | grep '^wall=')"
    wall="$(sed -E 's/.*wall=([0-9.]+).*/\1/' <<<"$line")"
    cpu="$(sed -E 's/.*cpu=([0-9.]+).*/\1/' <<<"$line")"
    sum="$(sed -E 's/.*checksum=([0-9.e+-]+).*/\1/' <<<"$line")"
    gf="$(sed -E 's/.*gflops=([0-9.]+).*/\1/' <<<"$line")"
    echo "$host,$machine,$N,$r,$wall,$cpu,$sum,$gf" | tee -a "$OUT"
  done
done
echo "wrote $OUT"

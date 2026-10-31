#!/usr/bin/env bash
# EE542 Lab 8 Steps 7.8-7.10: repeat the table's tests so one short run does not
# set the number. Runs on the Mac after sourcing data/raw/part7_hosts.env.
# Keeps each round as data/raw/rep/part7_<test>_<role>_<host>_r<i>.log on the nodes.
#   ./repeat_rdma.sh 3 gpu_lat gpu_put_bw cpu_lat cpu_bw
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
rounds="$1"; shift
"$here/cl.sh" both 'mkdir -p ~/lab8/data/raw/rep'
for i in $(seq 1 "$rounds"); do
  for t in "$@"; do
    "$here/cl.sh" rdma "$t" > /dev/null 2>&1
    "$here/cl.sh" both "cd ~/lab8/data/raw && for f in part7_${t}_client_*.log part7_${t}_server_*.log; do [ -e \"\$f\" ] && cp \"\$f\" rep/\${f%.log}_r$i.log; done; true"
    echo "$(date +%H:%M:%S) round $i $t done"
  done
done

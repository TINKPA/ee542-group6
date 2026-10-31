#!/usr/bin/env bash
# EE542 Lab 8 Part 7: drive the two CloudLab d7525 nodes from the Mac.
#   export N0=<node0 hostname> N1=<node1 hostname>     (from the experiment's List View)
#   ./cl.sh push                  # code/part7 -> ~/lab8/code/part7 on both nodes
#   ./cl.sh both '<cmd>'          # run on node0 and node1 in parallel
#   ./cl.sh 0|1 '<cmd>'           # run on one node
#   ./cl.sh rdma <test> [...]     # server on node0, client on node1 (rdma_one.sh tests)
#   ./cl.sh setup                 # setup_node.sh on both nodes, detached
#   ./cl.sh status                # last lines of both setup logs
#   ./cl.sh pull                  # data/raw/part7_* from both nodes back here
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lab="$(cd "$here/../.." && pwd)"
U="${CLUSER:-huacongt}"
OPTS=(-i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=15)
node() { case "$1" in 0) echo "$N0" ;; 1) echo "$N1" ;; esac; }
on() { local n="$1"; shift; ssh "${OPTS[@]}" "$U@$(node "$n")" "$@"; }
P=lab8/code/part7
case "${1:-}" in
  push) for n in 0 1; do
          on "$n" "mkdir -p ~/$P ~/lab8/data/raw"
          tar -C "$here" -cf - --exclude .DS_Store . | on "$n" "tar -C ~/$P -xf -"
        done ;;
  pull) for n in 0 1; do on "$n" "cd ~/lab8/data/raw && tar -cf - part7_* rep 2>/dev/null" | tar -C "$lab/data/raw" -xf -; done
        ls "$lab/data/raw" | grep part7_ ;;
  setup) $0 both 'nohup ~/lab8/code/part7/setup_node.sh > ~/lab8/data/raw/part7_setup_$(hostname -s).log 2>&1 < /dev/null & echo started' ;;
  status) $0 both 'tail -n 3 ~/lab8/data/raw/part7_setup_*.log' ;;
  both) shift; on 0 "$@" 2>&1 | sed 's/^/[node0] /' & on 1 "$@" 2>&1 | sed 's/^/[node1] /'; wait ;;
  0|1)  n="$1"; shift; on "$n" "$@" ;;
  rdma) shift
        for t in "$@"; do
          echo "=== $t"
          on 0 "~/$P/rdma_one.sh $t server"; sleep "${WAIT:-8}"   # server needs to be listening first
          on 1 "TMO=${TMO:-300} ~/$P/rdma_one.sh $t client"
          # bw servers check the received data and print only after Ctrl+C
          on 0 "sudo kill -INT \$(cat /tmp/part7_$t.pid) 2>/dev/null; sleep 10; sudo kill -9 \$(cat /tmp/part7_$t.pid) 2>/dev/null; cat ~/lab8/data/raw/part7_${t}_server_*.log"
        done ;;
  *) sed -n '2,11p' "$0"; exit 1 ;;
esac

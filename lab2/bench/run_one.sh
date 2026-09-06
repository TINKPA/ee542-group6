#!/bin/bash
# EE542 Lab2 — run ONE 1GiB transfer: client(sender) -> server(receiver).
# Usage: run_one.sh <case> <rep> <rate_mbps> <results_dir>
# Emits a one-line JSON record to <results_dir>/runs.jsonl
set -u
CASE=$1; REP=$2; RATE=$3; RD=$4
SVR=192.168.10.100; CLI=192.168.20.100; PORT=$((5700 + RANDOM % 200))
SSH="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=8"
TAG="c${CASE}_r${REP}"
mkdir -p "$RD"

# clock offset (server_real - client_real): each VM bracketed against host clock
# (midpoint method, best-of-5 by tightest RTT); error bounded by half the min RTT.
off_one() {
  local host=$1 best_rtt="" best_est="" i t0 tx t1 rtt est
  for i in 1 2 3 4 5; do
    t0=$(python3 -c 'import time;print(time.time_ns())')
    tx=$($SSH ubuntu@$host 'date +%s%N' 2>/dev/null) || continue
    t1=$(python3 -c 'import time;print(time.time_ns())')
    rtt=$((t1 - t0)); est=$(python3 -c "print($tx - ($t0 + $t1)//2)")
    if [ -z "$best_rtt" ] || [ "$rtt" -lt "$best_rtt" ]; then best_rtt=$rtt; best_est=$est; fi
  done
  echo "${best_est:-0}"
}
OFF_MS=$(python3 -c "print(($(off_one $SVR) - $(off_one $CLI))/1e6)")

$SSH ubuntu@$SVR "pkill -x ftr 2>/dev/null; rm -f /home/ubuntu/recv.bin; nohup /home/ubuntu/ftr recv /home/ubuntu/recv.bin --port $PORT > /tmp/recv_${TAG}.log 2>&1 & echo ok" >/dev/null 2>&1
sleep 2
$SSH ubuntu@$CLI "pkill -x ftr 2>/dev/null; /home/ubuntu/ftr send /home/ubuntu/data.bin $SVR --port $PORT --rate-mbps $RATE" \
  > "$RD/send_${TAG}.log" 2> "$RD/send_${TAG}.err"
SEND_RC=$?
sleep 2
$SSH ubuntu@$SVR "cat /tmp/recv_${TAG}.log" > "$RD/recv_${TAG}.log" 2>/dev/null

T_FIRST=$(grep T_FIRST_BIT_NS "$RD/send_${TAG}.log" | awk '{print $2}')
T_LAST=$(grep T_LAST_BIT_NS "$RD/recv_${TAG}.log" | awk '{print $2}')
SPAN=$(grep RECV_SPAN_S "$RD/recv_${TAG}.log" | awk '{print $2}')
ROUNDS=$(grep "^ROUNDS" "$RD/send_${TAG}.log" | awk '{print $2}')
PKTS=$(grep "^TOTAL_PKTS" "$RD/send_${TAG}.log" | awk '{print $2}')
ELAP=$(grep "^SENDER_ELAPSED_S" "$RD/send_${TAG}.log" | awk '{print $2}')

MD5S=$($SSH ubuntu@$SVR 'md5sum /home/ubuntu/recv.bin 2>/dev/null' 2>/dev/null | awk '{print $1}')
MD5C="4c613be268859aa982f6dbcd99c922a0"  # known md5 of data.bin

ONEWAY="null"
if [ -n "${T_FIRST:-}" ] && [ -n "${T_LAST:-}" ]; then
  ONEWAY=$(python3 -c "print((int($T_LAST)-int($T_FIRST))/1e9 - ($OFF_MS)/1e3)")
fi
OK=false; [ "$MD5S" = "$MD5C" ] && OK=true

echo "{\"case\":$CASE,\"rep\":$REP,\"rate\":$RATE,\"oneway_s\":$ONEWAY,\"recv_span_s\":${SPAN:-null},\"sender_elapsed_s\":${ELAP:-null},\"rounds\":${ROUNDS:-null},\"total_pkts\":${PKTS:-null},\"md5_ok\":$OK,\"clk_off_ms\":$OFF_MS,\"send_rc\":$SEND_RC}" >> "$RD/runs.jsonl"
echo "[$TAG] oneway=${ONEWAY}s span=${SPAN:-?}s rounds=${ROUNDS:-?} pkts=${PKTS:-?} md5_ok=$OK"

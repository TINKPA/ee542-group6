#!/bin/bash
# EE542 Lab2 — run ONE 1GiB transfer on the AWS topology: client(sender) -> server(receiver).
# Usage: aws_run.sh <case> <mtu> <rep> <proto:ftr|ltr|scp> <rate_mbps> [results_dir]
# Emits one JSON line to <results_dir>/runs.jsonl. Assumes aws_case.sh already applied.
# Clock offset (server_real - client_real) is bracketed from the Mac against both
# nodes (midpoint, best-of-5); with chrony/AWS Time Sync on both it should be ~0.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/hosts.env"
CASE=$1; MTU=$2; REP=$3; PROTO=$4; RATE=$5; RD=${6:-$DIR/results}
PORT=$((5700 + RANDOM % 200))
SSH="ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8"
TAG="c${CASE}_m${MTU}_${PROTO}_r${REP}"
TOPO=$([ -n "${ROUTER_PUB:-}" ] && echo 3node || echo 2node)
mkdir -p "$RD"

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
OFF_MS=$(python3 -c "print(($(off_one $SERVER_PUB) - $(off_one $CLIENT_PUB))/1e6)")

EXP=$($SSH ubuntu@$CLIENT_PUB 'cat data.md5' 2>/dev/null)

case $PROTO in
ftr|ltr)
  LOSSARG=""
  if [ "$PROTO" = ltr ]; then
    case $CASE in 1) LOSSARG="--loss 1";; 2) LOSSARG="--loss 20";; *) LOSSARG="--loss 0";; esac
  fi
  $SSH ubuntu@$SERVER_PUB "pkill -x $PROTO 2>/dev/null; rm -f /home/ubuntu/recv.bin; nohup /home/ubuntu/$PROTO recv /home/ubuntu/recv.bin --port $PORT > /tmp/recv_${TAG}.log 2>&1 & echo ok" >/dev/null 2>&1
  sleep 2
  $SSH ubuntu@$CLIENT_PUB "pkill -x $PROTO 2>/dev/null; /home/ubuntu/$PROTO send /home/ubuntu/data.bin $SERVER_PRIV --port $PORT --rate-mbps $RATE --mtu $MTU $LOSSARG" \
    > "$RD/send_${TAG}.log" 2> "$RD/send_${TAG}.err"
  SEND_RC=$?
  sleep 2
  $SSH ubuntu@$SERVER_PUB "cat /tmp/recv_${TAG}.log" > "$RD/recv_${TAG}.log" 2>/dev/null
  T_FIRST=$(grep T_FIRST_BIT_NS "$RD/send_${TAG}.log" | awk '{print $2}')
  T_LAST=$(grep T_LAST_BIT_NS "$RD/recv_${TAG}.log" | awk '{print $2}')
  ;;
scp)
  $SSH ubuntu@$SERVER_PUB 'rm -f /home/ubuntu/recv.bin' 2>/dev/null
  # pollers: receiver-side file size at 1 Hz (completion curve) and sender-side
  # ss -tin at 0.2 Hz (cwnd/RTO evidence). Flag-file lifetime controls both.
  $SSH ubuntu@$SERVER_PUB "touch /tmp/poll_${TAG}; nohup bash -c 'while [ -f /tmp/poll_${TAG} ]; do echo \$(date +%s),\$(stat -c %s /home/ubuntu/recv.bin 2>/dev/null || echo 0); sleep 1; done' > /tmp/scp_prog_${TAG}.csv 2>/dev/null & echo ok" >/dev/null
  $SSH ubuntu@$CLIENT_PUB "touch /tmp/poll_${TAG}; nohup bash -c 'while [ -f /tmp/poll_${TAG} ]; do echo ===\$(date +%s%N); ss -tin dst $SERVER_PRIV; sleep 5; done' > /tmp/scp_ss_${TAG}.log 2>/dev/null & echo ok" >/dev/null
  T_FIRST=$($SSH ubuntu@$CLIENT_PUB 'date +%s%N')
  $SSH ubuntu@$CLIENT_PUB "timeout ${SCPCAP:-600} scp -q -o StrictHostKeyChecking=accept-new /home/ubuntu/data.bin ubuntu@$SERVER_PRIV:/home/ubuntu/recv.bin" \
    > "$RD/send_${TAG}.log" 2> "$RD/send_${TAG}.err"
  SEND_RC=$?
  T_LAST=$($SSH ubuntu@$SERVER_PUB 'date +%s%N')
  $SSH ubuntu@$SERVER_PUB "rm -f /tmp/poll_${TAG}" 2>/dev/null
  $SSH ubuntu@$CLIENT_PUB "rm -f /tmp/poll_${TAG}" 2>/dev/null
  sleep 2
  $SSH ubuntu@$SERVER_PUB "cat /tmp/scp_prog_${TAG}.csv" > "$RD/scp_prog_${TAG}.csv" 2>/dev/null || true
  $SSH ubuntu@$CLIENT_PUB "cat /tmp/scp_ss_${TAG}.log" > "$RD/scp_ss_${TAG}.log" 2>/dev/null || true
  ;;
*) echo "bad proto"; exit 1;;
esac

MD5S=$($SSH ubuntu@$SERVER_PUB 'md5sum /home/ubuntu/recv.bin 2>/dev/null' 2>/dev/null | awk '{print $1}')
OK=false; [ -n "$EXP" ] && [ "$MD5S" = "$EXP" ] && OK=true
ONEWAY="null"
if [ -n "${T_FIRST:-}" ] && [ -n "${T_LAST:-}" ]; then
  ONEWAY=$(python3 -c "print((int($T_LAST)-int($T_FIRST))/1e9 - ($OFF_MS)/1e3)")
fi
MBPS="null"
[ "$ONEWAY" != "null" ] && MBPS=$(python3 -c "print(round(1073741824*8/1e6/$ONEWAY,2))")

echo "{\"topo\":\"$TOPO\",\"case\":$CASE,\"mtu\":$MTU,\"proto\":\"$PROTO\",\"rep\":$REP,\"rate\":$RATE,\"oneway_s\":$ONEWAY,\"mbps\":$MBPS,\"md5_ok\":$OK,\"clk_off_ms\":$OFF_MS,\"send_rc\":${SEND_RC:-null}}" >> "$RD/runs.jsonl"
echo "[$TAG/$TOPO] oneway=${ONEWAY}s mbps=$MBPS md5_ok=$OK clk_off=${OFF_MS}ms"

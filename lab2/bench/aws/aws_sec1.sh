#!/bin/bash
# EE542 Lab2 — handout §1 verification for ONE case on the AWS topology:
# apply case+mtu (aws_case.sh), then ping -i0.2 -c200 both directions and
# iperf2 TCP+UDP both directions. Logs -> results/sec1_c<C>_m<MTU>/.
# Usage: aws_sec1.sh <1|2|3> <mtu> [iperf_dur_s]
set -eu
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/hosts.env"
C=${1:?case}; MTU=${2:?mtu}; DUR=${3:-10}
OUT="$DIR/results/sec1_c${C}_m${MTU}"; mkdir -p "$OUT"
SSH="ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8"

"$DIR/aws_case.sh" $C $MTU | tee "$OUT/case_set.txt"
$SSH ubuntu@$SERVER_PUB 'pkill -x iperf 2>/dev/null; sleep 0.3; nohup iperf -s >/dev/null 2>&1 & nohup iperf -s -u >/dev/null 2>&1 & echo ok' >/dev/null
$SSH ubuntu@$CLIENT_PUB 'pkill -x iperf 2>/dev/null; sleep 0.3; nohup iperf -s >/dev/null 2>&1 & nohup iperf -s -u >/dev/null 2>&1 & echo ok' >/dev/null
sleep 1
echo "== ping c->s (200x) =="; $SSH ubuntu@$CLIENT_PUB "ping -i 0.2 -c 200 $SERVER_PRIV" > "$OUT/ping_c2s.txt" 2>&1 || true; tail -2 "$OUT/ping_c2s.txt"
echo "== ping s->c (200x) =="; $SSH ubuntu@$SERVER_PUB "ping -i 0.2 -c 200 $CLIENT_PRIV" > "$OUT/ping_s2c.txt" 2>&1 || true; tail -2 "$OUT/ping_s2c.txt"
echo "== TCP c->s ==";  $SSH ubuntu@$CLIENT_PUB "iperf -c $SERVER_PRIV -t $DUR" > "$OUT/tcp_c2s.txt" 2>&1 || true; tail -1 "$OUT/tcp_c2s.txt"
echo "== TCP s->c ==";  $SSH ubuntu@$SERVER_PUB "iperf -c $CLIENT_PRIV -t $DUR" > "$OUT/tcp_s2c.txt" 2>&1 || true; tail -1 "$OUT/tcp_s2c.txt"
echo "== UDP c->s ==";  $SSH ubuntu@$CLIENT_PUB "iperf -u -c $SERVER_PRIV -b 100mbit -t $DUR" > "$OUT/udp_c2s.txt" 2>&1 || true; tail -3 "$OUT/udp_c2s.txt"
echo "== UDP s->c ==";  $SSH ubuntu@$SERVER_PUB "iperf -u -c $CLIENT_PRIV -b 100mbit -t $DUR" > "$OUT/udp_s2c.txt" 2>&1 || true; tail -3 "$OUT/udp_s2c.txt"
$SSH ubuntu@$SERVER_PUB 'pkill -x iperf' 2>/dev/null || true
$SSH ubuntu@$CLIENT_PUB 'pkill -x iperf' 2>/dev/null || true
echo "SEC1_C${C}_M${MTU}_DONE -> $OUT/"

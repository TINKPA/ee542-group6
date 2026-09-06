#!/bin/bash
# EE542 Lab2 — official measurement matrix on the AWS 3-node topology.
# Phase 1: ftr, case {1,2,3} x MTU {1500,9001} x 3 reps (pacing per 8/29 sweep:
#          c1/c2 = 95 Mbps robust plateau, c3 = 78 under the 80 Mbit bottleneck).
# Phase 2: scp baseline, MTU 1500, 1 rep per case, 10-min DNF cap (case 2 DNF'd
#          at 20 min locally). Also retakes the §1 case-2 UDP c->s server report
#          that iperf2 garbled under 20% loss.
# All records -> results/runs.jsonl (aws_run.sh). Usage: aws_matrix.sh
set -eu
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/hosts.env"
RD="$DIR/results"
SSH="ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8"

rate_for() { case "$1" in 3) echo 78;; *) echo 95;; esac; }

echo "== phase 1: ftr matrix =="
for MTU in 1500 9001; do
  for C in 1 2 3; do
    "$DIR/aws_case.sh" $C $MTU
    R=$(rate_for $C)
    for REP in 1 2 3; do
      "$DIR/aws_run.sh" $C $MTU $REP ftr $R "$RD"
    done
  done
done

echo "== phase 2: scp baselines (mtu 1500) =="
# client -> server ssh key for scp over the shaped private path (idempotent)
CK=$($SSH ubuntu@$CLIENT_PUB 'test -f ~/.ssh/id_ed25519 || ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -q; cat ~/.ssh/id_ed25519.pub')
$SSH ubuntu@$SERVER_PUB "grep -qF '$CK' ~/.ssh/authorized_keys || echo '$CK' >> ~/.ssh/authorized_keys; echo key_ok"
for C in 1 2 3; do
  "$DIR/aws_case.sh" $C 1500
  if [ "$C" = 2 ]; then
    echo "== retake §1 case2 UDP c->s =="
    $SSH ubuntu@$SERVER_PUB 'pkill -x iperf 2>/dev/null; sleep 0.3; nohup iperf -s -u >/dev/null 2>&1 & echo ok' >/dev/null
    sleep 1
    $SSH ubuntu@$CLIENT_PUB "iperf -u -c $SERVER_PRIV -b 100mbit -t 10" > "$RD/sec1_c2_m1500/udp_c2s.txt" 2>&1 || true
    tail -3 "$RD/sec1_c2_m1500/udp_c2s.txt"
    $SSH ubuntu@$SERVER_PUB 'pkill -x iperf' 2>/dev/null || true
  fi
  "$DIR/aws_run.sh" $C 1500 1 scp 0 "$RD"
done
echo "== phase 3: pacing sweep (case 2, mtu 1500; rep=9 marks sweep rows; 95 already has 3 reps) =="
"$DIR/aws_case.sh" 2 1500
for R in 85 90 93 97 99; do
  "$DIR/aws_run.sh" 2 1500 9 ftr $R "$RD"
done
echo "MATRIX_DONE"

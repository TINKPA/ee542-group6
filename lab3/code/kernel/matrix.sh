#!/bin/bash
# EE542 Lab3 Part 3 §6 -- "if you made multiple modifications, test them
# separately and combined".  The two modifications are
#   (1) net.ipv4.tcp_no_rto_backoff=1   -- patched kernel, no RTO doubling
#   (2) tcp_congestion_control=ee542c   -- loadable module, cwnd pinned
# so the 2x2 grid below is exactly that requirement, run at the full-credit
# operating point (100 Mbps, 200 ms RTT, 20 % loss each way).
#
# Both knobs are runtime settings on one kernel binary and one boot, so nothing
# but the knob changes between cells -- no recompile, no reboot, no drift in
# config or compiler between the "with" and "without" arms.
#
# Each cell is a capped scp; throughput = bytes that landed on the server / cap.
# `ss -tin` is sampled every 5 s on the sender, which is where the effect of (1)
# is visible directly: rto stops doubling.
#
# Usage: matrix.sh [cap_s]     default 120
#        matrix.sh full        untruncated 1 GiB with both modifications on
# Reads hosts.env written by ../../../lab2/code/aws/aws_lab.sh.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
AWS="$DIR/../../../lab2/code/aws"
. "$AWS/hosts.env"
SSH="ssh -o ServerAliveInterval=15 -o ServerAliveCountMax=4 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
RD="$DIR/../../data/raw/matrix"; mkdir -p "$RD"
CSV="$RD/matrix.csv"
RTT=200; LOSS=20
[ -f "$CSV" ] || echo "cc,no_rto_backoff,cap_s,bytes,mbps,bytes_sent,bytes_retrans,cwnd_last,rto_min_ms,rto_max_ms,ts" > "$CSV"

shaper() { # handout §3: router-only tbf 100 Mbps, netem as its child, MTU 1500
  for h in $CLIENT_PUB $SERVER_PUB; do
    $SSH ubuntu@$h 'for I in $(ip -o link | awk -F": " "{print \$2}" | grep -E "^(en|eth)"); do sudo tc qdisc del dev $I root 2>/dev/null; sudo ip link set dev $I mtu 1500; done'
  done
  $SSH ubuntu@$ROUTER_PUB "for I in \$(ip -o link | awk -F': ' '{print \$2}' | grep -E '^(en|eth)'); do
      sudo ip link set dev \$I mtu 1500; sudo tc qdisc del dev \$I root 2>/dev/null
      sudo tc qdisc add dev \$I root handle 1:0 tbf rate 100mbit latency 0.001ms burst 901555
      sudo tc qdisc add dev \$I parent 1:1 handle 10: netem delay $((RTT/2))ms loss ${LOSS}%
    done; sudo tc qdisc show | grep netem | head -1"
}

knobs() { # $1 = cc, $2 = no_rto_backoff
  $SSH ubuntu@$CLIENT_PUB "sudo sysctl -qw net.ipv4.tcp_congestion_control=$1 net.ipv4.tcp_no_rto_backoff=$2
    echo -n '  cc='; sysctl -n net.ipv4.tcp_congestion_control
    echo -n '  no_rto_backoff='; sysctl -n net.ipv4.tcp_no_rto_backoff"
}

sample_start() { $SSH ubuntu@$CLIENT_PUB "touch /tmp/poll_$1; nohup bash -c 'while [ -f /tmp/poll_$1 ]; do echo ===\$(date +%s); ss -tin dst $SERVER_PRIV; sleep 5; done' > /tmp/ss_$1.log 2>/dev/null & echo ok" >/dev/null; }
sample_stop()  { $SSH ubuntu@$CLIENT_PUB "rm -f /tmp/poll_$1"; sleep 1; $SSH ubuntu@$CLIENT_PUB "cat /tmp/ss_$1.log" > "$RD/ss_$1.log" 2>/dev/null; }

cell() { # $1 = cc, $2 = no_rto_backoff, $3 = cap s
  local CC=$1 NB=$2 CAP=$3 TAG="${1}_nb${2}"
  echo "== $TAG =="
  knobs $CC $NB
  $SSH ubuntu@$SERVER_PUB "rm -f /home/ubuntu/recv.bin" 2>/dev/null
  sample_start $TAG
  $SSH ubuntu@$CLIENT_PUB "timeout $CAP scp -q -o StrictHostKeyChecking=accept-new -o ConnectTimeout=$CAP /home/ubuntu/data.bin ubuntu@$SERVER_PRIV:/home/ubuntu/recv.bin" >/dev/null 2>&1
  local BYTES; BYTES=$($SSH ubuntu@$SERVER_PUB 'stat -c %s /home/ubuntu/recv.bin 2>/dev/null || echo 0')
  sample_stop $TAG
  local LAST SENT RETR CWND RMIN RMAX MBPS
  LAST=$(grep -E "cwnd:" "$RD/ss_$TAG.log" | tail -1)
  SENT=$(echo "$LAST" | grep -oE "bytes_sent:[0-9]+" | cut -d: -f2)
  RETR=$(echo "$LAST" | grep -oE "bytes_retrans:[0-9]+" | cut -d: -f2)
  CWND=$(echo "$LAST" | grep -oE "cwnd:[0-9]+" | cut -d: -f2)
  RMIN=$(grep -oE "rto:[0-9.]+" "$RD/ss_$TAG.log" | cut -d: -f2 | sort -g | head -1)
  RMAX=$(grep -oE "rto:[0-9.]+" "$RD/ss_$TAG.log" | cut -d: -f2 | sort -g | tail -1)
  MBPS=$(python3 -c "print(round($BYTES*8/1e6/$CAP,3))")
  echo "$CC,$NB,$CAP,$BYTES,$MBPS,${SENT:-0},${RETR:-0},${CWND:-0},${RMIN:-0},${RMAX:-0},$(date +%s)" >> "$CSV"
  echo "[$TAG] bytes=$BYTES -> $MBPS Mbps  cwnd=${CWND:-?} rto=${RMIN:-?}..${RMAX:-?}ms retrans=${RETR:-0}/${SENT:-0}"
}

full() { # untruncated 1 GiB, both modifications on, md5 verified
  local TAG=full_ee542c_nb1
  knobs ee542c 1
  $SSH ubuntu@$SERVER_PUB 'rm -f /home/ubuntu/recv.bin'
  sample_start $TAG
  local T0 T1 EL MD5 EXP
  T0=$(date +%s.%N)
  $SSH ubuntu@$CLIENT_PUB "timeout 2400 scp -q -o StrictHostKeyChecking=accept-new /home/ubuntu/data.bin ubuntu@$SERVER_PRIV:/home/ubuntu/recv.bin"
  T1=$(date +%s.%N)
  sample_stop $TAG
  EL=$(python3 -c "print(round($T1-$T0,2))")
  MD5=$($SSH ubuntu@$SERVER_PUB 'md5sum /home/ubuntu/recv.bin 2>/dev/null' | awk '{print $1}')
  EXP=$($SSH ubuntu@$CLIENT_PUB 'cat data.md5')
  echo "cc=ee542c no_rto_backoff=1 rtt_ms=$RTT loss=$LOSS full_1GiB_s=$EL mbps=$(python3 -c "print(round(1073741824*8/1e6/$EL,2))") md5_ok=$([ "$MD5" = "$EXP" ] && echo true || echo false)" | tee "$RD/$TAG.txt"
}

$SSH ubuntu@$CLIENT_PUB 'uname -r; sysctl -n net.ipv4.tcp_no_rto_backoff' || {
  echo "client is not running the patched kernel -- run install_client.sh first"; exit 1; }

case "${1:-matrix}" in
full) shaper; full;;
*)
  CAP=${1:-120}
  shaper
  for CC in cubic ee542c; do for NB in 0 1; do cell $CC $NB $CAP; done; done
  echo MATRIX_DONE
  column -s, -t "$CSV"
  ;;
esac

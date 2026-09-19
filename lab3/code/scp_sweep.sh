#!/bin/bash
# EE542 Lab3 Part 3 §2 — scp (TCP) throughput sweep over RTT x loss on the Lab 2 AWS
# 3-node topology (client 10.200.1.83 -> router -> server 10.200.2.48).
# Link shaping (SHAPER env, default lab3):
#   lab3 = Lab 3 handout §3: router-only tbf 100mbit latency 0.001ms burst 901555 on both
#          router ifaces, endpoints unshaped; netem "delay <RTT/2>ms loss <p>%" as child.
#   lab2 = Lab 2 handout: endpoints + router tbf burst 9015 (aws_case.sh 0), same netem.
#          burst 9015 holds ~1 frame, so TCP's own bursts are tail-dropped even at 0 % loss.
# Each cell: scp 1 GiB capped at CAP seconds; throughput = bytes landed on the
# server / CAP. Sender-side `ss -tin` sampled every 5 s -> ss_r<RTT>_l<loss>.log.
# CC env var (default: leave the node's current setting): sender-side congestion
# control to select before each transfer, e.g. CC=cubic or CC=ee542 (the module
# from kmod/, which must already be insmod'd). Results go to a per-CC directory.
# Usage: scp_sweep.sh baseline            # full 1 GiB at RTT 10 ms / 0 % (handout §2 first step)
#        scp_sweep.sh full <rtt_ms> <loss_pct>   # untruncated 1 GiB at that cell
#        scp_sweep.sh sweep [cap_s]       # 11 RTT x 6 loss grid, default cap 60 s
#        scp_sweep.sh cell <rtt_ms> <loss_pct> [cap_s]
# Reads hosts.env written by ../../lab2/code/aws/aws_lab.sh; results -> ../data/raw/sweep/.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
AWS="$DIR/../../lab2/code/aws"
. "$AWS/hosts.env"
SHAPER=${SHAPER:-lab3}
CC=${CC:-}
RD="$DIR/../data/raw/sweep$([ "$SHAPER" = lab2 ] && echo _lab2shaper)${CC:+_$CC}"; mkdir -p "$RD"
SSH="ssh -o ServerAliveInterval=15 -o ServerAliveCountMax=4 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
CSV="$RD/sweep.csv"
[ -f "$CSV" ] || echo "rtt_ms,loss_pct,cap_s,bytes,mbps,bytes_sent,bytes_retrans,cwnd_last,rto_last_ms,ts" > "$CSV"

shaper() { # one-time: MTU 1500 everywhere, tbf per SHAPER mode
  if [ "$SHAPER" = lab2 ]; then "$AWS/aws_case.sh" 0 1500 >/dev/null; return; fi
  for h in $CLIENT_PUB $SERVER_PUB; do
    $SSH ubuntu@$h 'for I in $(ip -o link | awk -F": " "{print \$2}" | grep -E "^(en|eth)"); do sudo tc qdisc del dev $I root 2>/dev/null; sudo ip link set dev $I mtu 1500; done'
  done
  $SSH ubuntu@$ROUTER_PUB 'for I in $(ip -o link | awk -F": " "{print \$2}" | grep -E "^(en|eth)"); do
      sudo ip link set dev $I mtu 1500; sudo tc qdisc del dev $I root 2>/dev/null
      sudo tc qdisc add dev $I root handle 1:0 tbf rate 100mbit latency 0.001ms burst 901555
      sudo tc qdisc add dev $I parent 1:1 handle 10: netem delay 0ms loss 0%
    done; sudo tc qdisc show | grep -c tbf'
}
set_cc() { # select the sender-side congestion control, if CC is set
  [ -z "$CC" ] && return 0
  $SSH ubuntu@$CLIENT_PUB "sudo sysctl -qw net.ipv4.tcp_congestion_control=$CC"
  echo "  cc=$($SSH ubuntu@$CLIENT_PUB 'sysctl -n net.ipv4.tcp_congestion_control')"
}
set_link() { # $1 = RTT ms (split half per direction), $2 = loss %
  local d; d=$(python3 -c "print($1/2)")
  $SSH ubuntu@$ROUTER_PUB "for IF in \$(ip -o link | awk -F': ' '{print \$2}' | grep -E '^(en|eth)'); do
      sudo tc qdisc replace dev \$IF parent 1:1 handle 10: netem delay ${d}ms loss ${2}%
    done; sudo tc qdisc show | grep netem | head -1"
}

full() { # $1 = RTT ms, $2 = loss %, $3 = output basename -- untruncated 1 GiB, md5 verified
  local RTT=$1 LOSS=$2 OUT=$3 TAG="full_r${1}_l${2}"
  set_cc
  set_link $RTT $LOSS
  $SSH ubuntu@$SERVER_PUB 'rm -f /home/ubuntu/recv.bin'
  $SSH ubuntu@$CLIENT_PUB "touch /tmp/poll_$TAG; nohup bash -c 'while [ -f /tmp/poll_$TAG ]; do echo ===\$(date +%s); ss -tin dst 10.200.2.48; sleep 10; done' > /tmp/ss_$TAG.log 2>/dev/null & echo ok" >/dev/null
  local T0 T1 EL MD5 EXP
  T0=$(date +%s.%N)
  $SSH ubuntu@$CLIENT_PUB "timeout 2400 scp -q -o StrictHostKeyChecking=accept-new /home/ubuntu/data.bin ubuntu@10.200.2.48:/home/ubuntu/recv.bin"
  T1=$(date +%s.%N)
  $SSH ubuntu@$CLIENT_PUB "rm -f /tmp/poll_$TAG" 2>/dev/null
  sleep 1; $SSH ubuntu@$CLIENT_PUB "cat /tmp/ss_$TAG.log" > "$RD/ss_$TAG.log" 2>/dev/null
  EL=$(python3 -c "print(round($T1-$T0,2))")
  MD5=$($SSH ubuntu@$SERVER_PUB 'md5sum /home/ubuntu/recv.bin 2>/dev/null' | awk '{print $1}')
  EXP=$($SSH ubuntu@$CLIENT_PUB 'cat data.md5')
  echo "shaper=$SHAPER cc=${CC:-default} rtt_ms=$RTT loss=$LOSS full_1GiB_s=$EL mbps=$(python3 -c "print(round(1073741824*8/1e6/$EL,2))") md5_ok=$([ "$MD5" = "$EXP" ] && echo true || echo false)" | tee "$RD/$OUT"
}

cell() { # $1 = RTT ms, $2 = loss %, $3 = cap s
  local RTT=$1 LOSS=$2 CAP=$3 TAG="r${1}_l${2}"
  set_cc
  set_link $RTT $LOSS
  $SSH ubuntu@$SERVER_PUB 'rm -f /home/ubuntu/recv.bin' 2>/dev/null
  $SSH ubuntu@$CLIENT_PUB "touch /tmp/poll_$TAG; nohup bash -c 'while [ -f /tmp/poll_$TAG ]; do echo ===\$(date +%s); ss -tin dst 10.200.2.48; sleep 5; done' > /tmp/ss_$TAG.log 2>/dev/null & echo ok" >/dev/null
  $SSH ubuntu@$CLIENT_PUB "timeout $CAP scp -q -o StrictHostKeyChecking=accept-new -o ConnectTimeout=$CAP /home/ubuntu/data.bin ubuntu@10.200.2.48:/home/ubuntu/recv.bin" >/dev/null 2>&1
  $SSH ubuntu@$CLIENT_PUB "rm -f /tmp/poll_$TAG" 2>/dev/null
  local BYTES; BYTES=$($SSH ubuntu@$SERVER_PUB 'stat -c %s /home/ubuntu/recv.bin 2>/dev/null || echo 0')
  sleep 1; $SSH ubuntu@$CLIENT_PUB "cat /tmp/ss_$TAG.log" > "$RD/ss_$TAG.log" 2>/dev/null
  local LAST; LAST=$(grep -E "cwnd:" "$RD/ss_$TAG.log" | tail -1)
  local SENT RETR CWND RTO
  SENT=$(echo "$LAST" | grep -oE "bytes_sent:[0-9]+" | cut -d: -f2); RETR=$(echo "$LAST" | grep -oE "bytes_retrans:[0-9]+" | cut -d: -f2)
  CWND=$(echo "$LAST" | grep -oE "cwnd:[0-9]+" | cut -d: -f2); RTO=$(echo "$LAST" | grep -oE "rto:[0-9]+" | cut -d: -f2)
  local MBPS; MBPS=$(python3 -c "print(round($BYTES*8/1e6/$CAP,3))")
  echo "$RTT,$LOSS,$CAP,$BYTES,$MBPS,${SENT:-0},${RETR:-0},${CWND:-0},${RTO:-0},$(date +%s)" >> "$CSV"
  echo "[$TAG] cap=${CAP}s bytes=$BYTES -> $MBPS Mbps  cwnd=${CWND:-?} rto=${RTO:-?}ms retrans=${RETR:-0}/${SENT:-0}"
}

case "${1:?baseline|full|sweep|cell}" in
baseline)
  shaper
  full 10 0 baseline.txt
  ;;
full)
  shaper
  full ${2:?rtt_ms} ${3:?loss_pct} "full_r${2}_l${3}.txt"
  ;;
sweep)
  CAP=${2:-60}
  shaper
  for LOSS in 0 5 10 15 20 25; do
    for RTT in 0 20 40 60 80 100 120 140 160 180 200; do
      grep -q "^$RTT,$LOSS,$CAP," "$CSV" && { echo "[r${RTT}_l${LOSS}] done, skip"; continue; }
      cell $RTT $LOSS $CAP
    done
  done
  echo SWEEP_DONE
  ;;
cell) shaper; cell $2 $3 ${4:-60};;
esac

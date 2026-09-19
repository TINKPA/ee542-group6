#!/bin/bash
# EE542 Lab3 Part 3 -- direct proof that the tcp_no_rto_backoff patch does what it
# claims, independent of any throughput measurement.
#
# Why this exists: in the 200 ms / 20 % matrix the RTO trace is not readable as
# evidence.  Every retransmission that does get through feeds a new RTT sample,
# the sampler only sees icsk_rto every 5 s, and at that loss rate the estimator
# itself produces multi-second RTOs, so "large RTO" and "backed-off RTO" are not
# distinguishable in the log.
#
# So isolate the timer.  Let a transfer establish on a clean 100 ms link, then
# blackhole the path (netem loss 100 %) and sample `ss` every 2 s.  With no data
# getting through there are no new RTT samples, so the estimator is frozen and
# every change in icsk_rto is the backoff and nothing else:
#   backoff on  -> a geometric sequence, doubling until the 120 s Linux cap
#   backoff off -> flat at the estimator's value
#
# Usage: backoff_probe.sh [cc, default cubic] [probe_s, default 70]
# Reads hosts.env; output -> ../../data/raw/backoff_probe/
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/../../../lab2/code/aws/hosts.env"
SSH="ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
RD="$DIR/../../data/raw/backoff_probe"; mkdir -p "$RD"
CC=${1:-cubic}; PROBE=${2:-70}

# WARNING: impair the router leg facing the SERVER only, never every interface.
# The other leg carries the Elastic IP, i.e. our own SSH session to the router;
# at 20 % loss that survives, at 100 % it does not, and the router then has to be
# rebooted through the EC2 API to clear the qdisc.  We learned this the direct way.
SIF=$($SSH ubuntu@$ROUTER_PUB "ip -br -4 addr | awk '/10.200.2./ {print \$1}'" | tr -d '\r')
[ -n "$SIF" ] || { echo "cannot find the router leg on 10.200.2.0/24"; exit 1; }

link() { # $1 = loss %, applied to the client -> server direction only
  $SSH ubuntu@$ROUTER_PUB "sudo tc qdisc replace dev $SIF parent 1:1 handle 10: netem delay 50ms loss ${1}%" >/dev/null
}

setup() {
  for h in $CLIENT_PUB $SERVER_PUB; do
    $SSH ubuntu@$h 'for I in $(ip -o link | awk -F": " "{print \$2}" | grep -E "^(en|eth)"); do sudo tc qdisc del dev $I root 2>/dev/null; sudo ip link set dev $I mtu 1500; done'
  done
  $SSH ubuntu@$ROUTER_PUB "for I in \$(ip -o link | awk -F': ' '{print \$2}' | grep -E '^(en|eth)'); do
      sudo ip link set dev \$I mtu 1500; sudo tc qdisc del dev \$I root 2>/dev/null
      sudo tc qdisc add dev \$I root handle 1:0 tbf rate 100mbit latency 0.001ms burst 901555
      sudo tc qdisc add dev \$I parent 1:1 handle 10: netem delay 50ms loss 0%
    done" >/dev/null
}

arm() { # $1 = no_rto_backoff
  local NB=$1 TAG="${CC}_nb${1}"   # note: ${NB} cannot be used here, local expands its
                                   # whole argument list before assigning any of it
  echo "== $TAG =="
  $SSH ubuntu@$CLIENT_PUB "sudo sysctl -qw net.ipv4.tcp_congestion_control=$CC net.ipv4.tcp_no_rto_backoff=$NB"
  link 0
  $SSH ubuntu@$SERVER_PUB 'rm -f /home/ubuntu/recv.bin'
  $SSH ubuntu@$CLIENT_PUB "nohup timeout $((PROBE+30)) scp -q -o StrictHostKeyChecking=accept-new /home/ubuntu/data.bin ubuntu@$SERVER_PRIV:/home/ubuntu/recv.bin >/dev/null 2>&1 & echo started" >/dev/null
  sleep 12
  echo "  pre-blackhole: $($SSH ubuntu@$CLIENT_PUB "ss -tin dst $SERVER_PRIV | grep -oE 'rto:[0-9]+ rtt:[0-9./]+' | head -1")"
  link 100
  $SSH ubuntu@$CLIENT_PUB "for i in \$(seq 1 $((PROBE/2))); do echo ===\$(date +%s); ss -tin dst $SERVER_PRIV; sleep 2; done" > "$RD/ss_$TAG.log"
  link 0
  $SSH ubuntu@$CLIENT_PUB "pkill -f 'scp -q' 2>/dev/null; true" >/dev/null
  echo "  rto sequence after blackhole:"
  grep -oE "rto:[0-9]+" "$RD/ss_$TAG.log" | cut -d: -f2 | uniq | tr '\n' ' '; echo
}

setup
arm 0
arm 1
echo PROBE_DONE

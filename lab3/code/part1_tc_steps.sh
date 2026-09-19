#!/bin/bash
# EE542 Lab3 Part 1 — the handout's iperf/tc step sequence on the AWS topology, client -> server.
# Steps (each: iperf3 TCP 10 s + iperf3 UDP 10 s at -b <bw>) with the qdisc on the CLIENT egress
# iface exactly as the handout writes them (eth0 == client's primary iface here):
#   0 clean            tc qdisc del ... root
#   1 delay100         tc qdisc add dev eth0 root netem delay 100ms
#   2 loss10           tc qdisc change dev eth0 root netem delay 0ms loss 10%
#   3 tbf100           tc qdisc del root; tc qdisc add dev eth0 root tbf rate 100mbit latency 1ms burst 9015
#   4 tbf100_mtu9001   same tbf, interface MTU 9001 (jumbo vs the burst-9015 bucket)
# Also records: ethtool -s speed 10 error, dmesg tail, MTU. Logs -> ../data/raw/part1/.
# Usage: part1_tc_steps.sh [udp_bw, default 200mbit as in the handout]
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"; AWS="$DIR/../../lab2/code/aws"; . "$AWS/hosts.env"
OUT="$DIR/../data/raw/part1"; mkdir -p "$OUT"; BW=${1:-200mbit}
SSH="ssh -o ServerAliveInterval=15 -o ServerAliveCountMax=4 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
C() { $SSH ubuntu@$CLIENT_PUB "$@"; }; S() { $SSH ubuntu@$SERVER_PUB "$@"; }; R() { $SSH ubuntu@$ROUTER_PUB "$@"; }
IF=$(C 'ip -o -4 route show default | awk "{print \$5}" | head -1')
# clean slate on all three (router netem from the sweep must go too)
for h in $CLIENT_PUB $SERVER_PUB $ROUTER_PUB; do
  $SSH ubuntu@$h 'for I in $(ip -o link | awk -F": " "{print \$2}" | grep -E "^(en|eth)"); do sudo tc qdisc del dev $I root 2>/dev/null; sudo ip link set dev $I mtu 1500; done'
done
S 'pkill -x iperf3 2>/dev/null; sleep 0.3; nohup iperf3 -s >/dev/null 2>&1 & echo ok' >/dev/null; sleep 1
run() { # $1 = step name
  echo "== $1 =="; C "tc qdisc show dev $IF" | tee "$OUT/$1_qdisc.txt"
  C "iperf3 -c 10.200.2.48 -t 10 -J" > "$OUT/$1_tcp.json" 2>&1
  C "iperf3 -u -c 10.200.2.48 -b $BW -t 10 -J" > "$OUT/$1_udp.json" 2>&1
  python3 - "$OUT/$1_tcp.json" "$OUT/$1_udp.json" <<'PY'
import json,sys
t=json.load(open(sys.argv[1])); u=json.load(open(sys.argv[2]))
print(f"  TCP {t['end']['sum_sent']['bits_per_second']/1e6:8.2f} Mbps sent, retrans={t['end']['sum_sent'].get('retransmits','?')}")
s=u['end']['sum']; print(f"  UDP {s['bits_per_second']/1e6:8.2f} Mbps, lost {s['lost_percent']:.1f}%, jitter {s['jitter_ms']:.3f} ms")
PY
}
run 0_clean
C "sudo tc qdisc add dev $IF root netem delay 100ms";                    run 1_delay100
C "sudo tc qdisc change dev $IF root netem delay 0ms loss 10%";           run 2_loss10
C "sudo tc qdisc del dev $IF root; sudo tc qdisc add dev $IF root tbf rate 100mbit latency 1ms burst 9015"; run 3_tbf100
C "sudo ip link set dev $IF mtu 9001"; S "sudo ip link set dev \$(ip -o -4 route show default | awk '{print \$5}') mtu 9001"
R 'for I in $(ip -o link | awk -F": " "{print \$2}" | grep -E "^(en|eth)"); do sudo ip link set dev $I mtu 9001; done'
run 4_tbf100_mtu9001
C "sudo tc qdisc del dev $IF root; sudo ip link set dev $IF mtu 1500"
echo "== misc =="; { echo "### ethtool -s $IF speed 10"; C "sudo ethtool -s $IF speed 10 2>&1; echo rc=\$?"; echo "### ethtool -i"; C "ethtool -i $IF | head -3";
  echo "### dmesg (last 15)"; C "sudo dmesg -T | tail -15"; } | tee "$OUT/misc.txt"
S 'pkill -x iperf3' 2>/dev/null; echo PART1_DONE

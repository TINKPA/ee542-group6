#!/bin/bash
# EE542 Lab3 Part 3 -- is 10.75 Mbps TCP's limit, or scp's?
#
# The 2x2 matrix left ee542c at ~12 Mbps with the kernel reporting app_limited in
# 20 of 24 samples: cwnd pinned at 1730, rwnd_limited 1.4 %, computed send rate
# 99.5 Mbps, and yet no data to send.  That says the sender is starved from above,
# and the suspect is OpenSSH's own per-channel window, which advances only when a
# CHANNEL_WINDOW_ADJUST makes the round trip -- expensive at 200 ms with 20 % loss.
#
# That is an inference, so this script tests it by removing the application-layer
# window instead of arguing about it.  Same link, same congestion control, three
# senders that differ only in what sits above TCP:
#
#   iperf3   pure TCP stream, no application framing or windowing at all
#   nc       a real 1 GiB file transfer, MD5 verified, no application window
#   scp      the number we already have, for reference
#
# The handout asks for "FTP over TCP/IP", not for scp specifically, so nc is a
# legitimate reading of the requirement as well as a diagnostic.
#
# Prediction being tested: if the ssh channel window is the limit, iperf3 and nc
# land far above scp, near the erasure bound (1-p) x 100 Mbps = 80 Mbps.  If all
# three agree, the app_limited attribution is wrong and the cause is elsewhere.
#
# Usage: part3_transport.sh [cc, default ee542c] [secs for iperf3, default 30]
# Assumes the link is already shaped at 200 ms / 20 % (kernel/matrix.sh or
# scp_sweep.sh set_link do this).  Output -> ../data/raw/transport/
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/../../lab2/code/aws/hosts.env"
SSH="ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
RD="$DIR/../data/raw/transport"; mkdir -p "$RD"
CC=${1:-ee542c}; T=${2:-30}; ONLY=${3:-both}   # both | iperf3 | nc
CSV="$RD/transport.csv"
[ -f "$CSV" ] || echo "transport,cc,secs,bytes,mbps,md5_ok,ts" > "$CSV"

echo "== link and congestion control =="
$SSH ubuntu@$ROUTER_PUB "sudo tc qdisc show | grep netem | head -2"
$SSH ubuntu@$CLIENT_PUB "sudo sysctl -qw net.ipv4.tcp_congestion_control=$CC
  echo -n '  cc='; sysctl -n net.ipv4.tcp_congestion_control
  echo -n '  no_rto_backoff='; sysctl -n net.ipv4.tcp_no_rto_backoff 2>/dev/null || echo n/a"

if [ "$ONLY" = both ] || [ "$ONLY" = iperf3 ]; then
echo "== iperf3: pure TCP, no application layer =="
$SSH ubuntu@$SERVER_PUB 'pkill -x iperf3 2>/dev/null; sleep 0.3; nohup iperf3 -s >/dev/null 2>&1 & sleep 0.5; echo up' >/dev/null
IPJ=$($SSH ubuntu@$CLIENT_PUB "iperf3 -c $SERVER_PRIV -t $T -J 2>/dev/null")
IMBPS=$(echo "$IPJ" | python3 -c "import sys,json; d=json.load(sys.stdin); print(round(d['end']['sum_received']['bits_per_second']/1e6,2))" 2>/dev/null || echo 0)
IRETR=$(echo "$IPJ" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['end']['sum_sent']['retransmits'])" 2>/dev/null || echo 0)
echo "$IPJ" > "$RD/iperf3_$CC.json"
echo "  iperf3: $IMBPS Mbps  retransmits=$IRETR"
echo "iperf3,$CC,$T,-,$IMBPS,-,$(date +%s)" >> "$CSV"
fi

if [ "$ONLY" = both ] || [ "$ONLY" = nc ]; then
echo "== nc: a real 1 GiB file, MD5 verified, no application window =="
$SSH ubuntu@$SERVER_PUB "rm -f /home/ubuntu/recv_nc.bin; pkill -x nc 2>/dev/null; sleep 0.3
  nohup sh -c 'nc -l 5900 > /home/ubuntu/recv_nc.bin' >/dev/null 2>&1 & sleep 1
  pgrep -x nc >/dev/null || { echo NC_LISTENER_FAILED; exit 1; }
  echo listening"
T0=$(date +%s.%N)
$SSH ubuntu@$CLIENT_PUB "timeout 2400 sh -c 'nc -q 5 $SERVER_PRIV 5900 < /home/ubuntu/data.bin'"
T1=$(date +%s.%N)
sleep 3
NB=$($SSH ubuntu@$SERVER_PUB 'stat -c %s /home/ubuntu/recv_nc.bin 2>/dev/null || echo 0')
NEL=$(python3 -c "print(round($T1-$T0,2))")
NMD5=$($SSH ubuntu@$SERVER_PUB 'md5sum /home/ubuntu/recv_nc.bin 2>/dev/null' | awk '{print $1}')
EXP=$($SSH ubuntu@$CLIENT_PUB 'cat data.md5')
NMBPS=$(python3 -c "print(round($NB*8/1e6/$NEL,2))")
OK=$([ "$NMD5" = "$EXP" ] && echo true || echo false)
echo "  nc: $NB bytes in ${NEL}s -> $NMBPS Mbps  md5_ok=$OK"
echo "nc,$CC,$NEL,$NB,$NMBPS,$OK,$(date +%s)" >> "$CSV"
fi

echo
echo "== summary (scp at this cell, for reference, is in ../data/raw/matrix/) =="
column -s, -t "$CSV"

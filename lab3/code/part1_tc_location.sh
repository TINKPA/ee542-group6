#!/bin/bash
# EE542 Lab3 Part 1, the handout's last bolded step:
#   "delete all the above set configurations on interfaces on client, server VM,
#    and do the same steps on [the router] on the interface not mapped to an
#    elastic IP.  Were you able to get the same observations as before in this
#    configuration?  Comment."
#
# Runs the handout's tc sequence at three locations, all impairing ONLY the
# client -> server direction so the arms are directly comparable:
#   endpoint    tc on the client's experiment NIC (eth0), stock offloads
#   endpoint_nooff  same, with tso/gso/gro off -- tests whether the qdisc seeing
#                   64 KB GSO super-packets (netem drops a whole skb, i.e. ~43
#                   MTU-sized segments at once) explains any difference
#   router      tc on the router's NON-EIP leg (10.0.2.10 side), which is the
#               egress for client -> server traffic
#
# Steps per arm (handout p.12-13):
#   0 clean, 1 netem delay 100ms, 2 netem change delay 0ms loss 10%,
#   3 tbf rate 100mbit latency 1ms burst 9015
# Each step: iperf3 TCP 10 s then iperf3 UDP 10 s at -b 200mbit.
#
# Usage: part1_tc_location.sh [udp_bw, default 200mbit]
# Reads aws/l3_hosts.env written by aws/lab3_topo.sh ips.  Output -> ../data/raw/part1_location/
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/aws/l3_hosts.env"
OUT="$DIR/../data/raw/part1_location"; mkdir -p "$OUT"
BW=${1:-200mbit}
SSH="ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
C() { $SSH ubuntu@$L3_CLIENT_PUB "$@"; }
S() { $SSH ubuntu@$L3_SERVER_PUB "$@"; }
R() { $SSH ubuntu@$L3_ROUTER_PUB "$@"; }

CIF=$(C "ip -o -4 addr show | awk '/$L3_CLIENT_EXP/{print \$2}' | head -1")
RIF=$(R "ip -o -4 addr show | awk '/$L3_ROUTER_B/{print \$2}' | head -1")   # the non-EIP leg
echo "client exp iface=$CIF   router non-EIP iface=$RIF"

clean_all() {
  C "sudo tc qdisc del dev $CIF root 2>/dev/null; sudo ethtool -K $CIF tso on gso on gro on 2>/dev/null; true"
  R "sudo tc qdisc del dev $RIF root 2>/dev/null; true"
}

measure() { # $1 = arm, $2 = step tag, $3 = host fn, $4 = iface
  local ARM=$1 TAG=$2 FN=$3 IF=$4
  $FN "tc qdisc show dev $IF" > "$OUT/${ARM}_${TAG}_qdisc.txt" 2>&1
  C "iperf3 -c $L3_SERVER_EXP -t 10 -J"                  > "$OUT/${ARM}_${TAG}_tcp.json" 2>&1
  C "iperf3 -u -c $L3_SERVER_EXP -b $BW -t 10 -J"        > "$OUT/${ARM}_${TAG}_udp.json" 2>&1
  python3 - "$OUT/${ARM}_${TAG}_tcp.json" "$OUT/${ARM}_${TAG}_udp.json" "$ARM/$TAG" <<'PY'
import json,sys
try:
    t=json.load(open(sys.argv[1])); u=json.load(open(sys.argv[2]))
    st=t['end']['streams'][0]['sender']; us=u['end']['sum']
    print(f"  {sys.argv[3]:28s} TCP {t['end']['sum_sent']['bits_per_second']/1e6:8.2f} Mbps "
          f"retx={t['end']['sum_sent'].get('retransmits','?'):>5} rtt={st.get('mean_rtt','?')}us | "
          f"UDP {us['bits_per_second']/1e6:7.2f} Mbps lost {us['lost_percent']:5.2f}%")
except Exception as e:
    print(f"  {sys.argv[3]:28s} PARSE_FAIL {e}")
PY
}

arm() { # $1 = arm name, $2 = host fn, $3 = iface, $4 = "nooff" to disable offloads
  local ARM=$1 FN=$2 IF=$3
  echo "== arm: $ARM (tc on $IF) =="
  clean_all
  if [ "${4:-}" = nooff ]; then
    C "sudo ethtool -K $CIF tso off gso off gro off; echo -n 'offloads: '; ethtool -k $CIF | grep -E '^(tcp-segmentation|generic-segmentation|generic-receive)-offload' | tr '\n' ' '; echo"
  fi
  $FN "ethtool -k $IF | grep -E '^(tcp-segmentation|generic-segmentation|generic-receive)-offload'" > "$OUT/${ARM}_offloads.txt" 2>&1
  measure $ARM 0_clean $FN $IF
  $FN "sudo tc qdisc add dev $IF root netem delay 100ms"                                    >/dev/null
  measure $ARM 1_delay100 $FN $IF
  $FN "sudo tc qdisc change dev $IF root netem delay 0ms loss 10%"                          >/dev/null
  measure $ARM 2_loss10 $FN $IF
  $FN "sudo tc qdisc del dev $IF root; sudo tc qdisc add dev $IF root tbf rate 100mbit latency 1ms burst 9015" >/dev/null
  measure $ARM 3_tbf100 $FN $IF
  clean_all
}

# Fail before burning 8 minutes of measurement if the tool is not there: the
# endpoints have no public IP on their experiment NIC, so a broken default route
# silently leaves apt unable to install iperf3 (seen on the first run).
for H in "$L3_CLIENT_PUB client" "$L3_SERVER_PUB server"; do
  set -- $H
  $SSH ubuntu@$1 'command -v iperf3 >/dev/null' || { echo "iperf3 missing on $2 ($1); run aws/lab3_topo.sh setup"; exit 1; }
done

S 'pkill -x iperf3 2>/dev/null; sleep 0.3; nohup iperf3 -s >/dev/null 2>&1 & echo ok' >/dev/null; sleep 1
# endpoint_nooff runs LAST: on the ENA driver "ethtool -K tso off" does not fully
# reverse ("tx-tcp-segmentation: off [requested on]" on the way back), so the arm
# that perturbs the NIC must not contaminate the other two.
arm endpoint        C "$CIF"
arm router          R "$RIF"
arm endpoint_nooff  C "$CIF" nooff
S 'pkill -x iperf3' 2>/dev/null
echo "LOCATION_DONE -> $OUT"

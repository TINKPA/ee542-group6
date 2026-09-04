#!/bin/bash
# EE542 Lab2 — apply one network case + MTU across the AWS nodes (handout §1 commands).
#   3-node mode (ROUTER_PUB set): endpoints tbf 100mbit; router both ifaces
#     tbf {100|80}mbit + netem child (delay/loss) — byte-identical to the handout.
#   2-node interim mode (no router yet): the router's tbf+netem is approximated on
#     BOTH endpoint egress ifaces (half delay per side, per-direction loss).
#     Interim numbers are for tuning only; official runs use 3-node mode.
# Usage: aws_case.sh <0|1|2|3> <mtu>       case 0 = rate limit only (verification)
set -eu
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/hosts.env"
C=${1:?case}; MTU=${2:?mtu}
S() { ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 "$@"; }

case $C in
  0) RRATE=100mbit; NETEM="";;
  1) RRATE=100mbit; NETEM="delay 5ms loss 1%";;
  2) RRATE=100mbit; NETEM="delay 100ms loss 20%";;
  3) RRATE=80mbit;  NETEM="delay 100ms";;
  *) echo "bad case"; exit 1;;
esac

# endpoint: discover primary iface, set MTU, egress tbf 100mbit (handout §1).
# In 2-node mode the router's tbf+netem is stacked on the endpoint as well.
ep() { # $1 = public ip
  if [ -n "${ROUTER_PUB:-}" ]; then
    S ubuntu@$1 "IF=\$(ip -o -4 route show default | awk '{print \$5}' | head -1)
      sudo ip link set dev \$IF mtu $MTU
      sudo tc qdisc del dev \$IF root 2>/dev/null || true
      sudo tc qdisc add dev \$IF root tbf rate 100mbit latency 0.001ms burst 9015
      echo \"EP_OK \$IF mtu=$MTU tbf=100mbit\""
  else
    S ubuntu@$1 "IF=\$(ip -o -4 route show default | awk '{print \$5}' | head -1)
      sudo ip link set dev \$IF mtu $MTU
      sudo tc qdisc del dev \$IF root 2>/dev/null || true
      sudo tc qdisc add dev \$IF root handle 1:0 tbf rate $RRATE latency 0.001ms burst 9015
      [ -n \"$NETEM\" ] && sudo tc qdisc add dev \$IF parent 1:1 handle 10: netem $NETEM || true
      echo \"EP_OK(2node) \$IF mtu=$MTU tbf=$RRATE netem=[$NETEM]\""
  fi
}

ep $CLIENT_PUB
ep $SERVER_PUB

if [ -n "${ROUTER_PUB:-}" ]; then
  S ubuntu@$ROUTER_PUB "PRI=\$(ip -o -4 route show default | awk '{print \$5}' | head -1)
    SEC=\$(ip -o -4 addr show | awk '/10\\.200\\.2\\.10/{print \$2}' | head -1)
    for IF in \$PRI \$SEC; do
      sudo ip link set dev \$IF mtu $MTU
      sudo tc qdisc del dev \$IF root 2>/dev/null || true
      sudo tc qdisc add dev \$IF root handle 1:0 tbf rate $RRATE latency 0.001ms burst 9015
      [ -n \"$NETEM\" ] && sudo tc qdisc add dev \$IF parent 1:1 handle 10: netem $NETEM || true
    done
    echo \"RTR_OK pri=\$PRI sec=\$SEC mtu=$MTU tbf=$RRATE netem=[$NETEM]\""
fi
echo "CASE${C}_SET mtu=$MTU mode=$([ -n "${ROUTER_PUB:-}" ] && echo 3node || echo 2node)"

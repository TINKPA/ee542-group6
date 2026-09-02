#!/usr/bin/env bash
set -euo pipefail

# Run on the VyOS ROUTER with sudo.
#
# Applies the Lab 2 mandatory network conditions.
#   Case 1: RTT  10ms, 1%  loss, router 100mbit
#   Case 2: RTT 200ms, 20% loss, router 100mbit
#   Case 3: RTT 200ms, no loss,  router  80mbit
#
# Structure required by the handout: TBF at root (handle 1:0) with netem
# attached as a child of the TBF class (parent 1:1 handle 10:).
#
# Topology mapping (Lab 1 carried forward):
#   eth1 -> server LAN 192.168.10.0/24   (handout calls this eth0)
#   eth2 -> client LAN 192.168.20.0/24   (handout calls this eth1)

IF_SERVER="${IF_SERVER:-eth1}"
IF_CLIENT="${IF_CLIENT:-eth2}"

# Handout specifies burst 9015. It must stay >= MTU, which is why 9015 works
# for both MTU 1500 and MTU 9001. If iperf comes in well under the cap, raise
# this (BURST=64000) and say so in the report.
BURST="${BURST:-9015}"
LATENCY="${LATENCY:-0.001ms}"

# netem defaults to a 1000-packet queue. At 200ms x 100mbit the BDP is ~2.5MB,
# roughly 1700 packets at MTU 1500, so the default limit silently drops traffic
# and caps throughput. Raise it. Set NETEM_LIMIT=1000 to see the default.
NETEM_LIMIT="${NETEM_LIMIT:-20000}"

usage() {
  cat <<USAGE
Usage:
  sudo ./apply-case.sh baseline   rate limit only, no delay or loss
  sudo ./apply-case.sh 1|2|3      apply a mandatory case
  sudo ./apply-case.sh clear      remove all shaping
  sudo ./apply-case.sh show       print current qdiscs

Environment overrides:
  IF_SERVER=$IF_SERVER  IF_CLIENT=$IF_CLIENT
  BURST=$BURST  LATENCY=$LATENCY  NETEM_LIMIT=$NETEM_LIMIT
USAGE
}

clear_qdisc() {
  for dev in "$IF_SERVER" "$IF_CLIENT"; do
    tc qdisc del dev "$dev" root 2>/dev/null || true
  done
}

show_qdisc() {
  for dev in "$IF_SERVER" "$IF_CLIENT"; do
    echo "--- $dev ---"
    tc qdisc show dev "$dev"
  done
}

# apply <rate_mbit> <one_way_delay_ms> <loss_percent|"">
apply() {
  local rate="$1" delay="$2" loss="$3"
  clear_qdisc
  for dev in "$IF_SERVER" "$IF_CLIENT"; do
    tc qdisc add dev "$dev" root handle 1:0 \
       tbf rate "${rate}mbit" latency "$LATENCY" burst "$BURST"
    if [ -n "$loss" ]; then
      tc qdisc add dev "$dev" parent 1:1 handle 10: \
         netem delay "${delay}ms" drop "${loss}%" limit "$NETEM_LIMIT"
    else
      tc qdisc add dev "$dev" parent 1:1 handle 10: \
         netem delay "${delay}ms" limit "$NETEM_LIMIT"
    fi
  done
}

case "${1:-}" in
  baseline)
      clear_qdisc
      for dev in "$IF_SERVER" "$IF_CLIENT"; do
        tc qdisc add dev "$dev" root handle 1:0            tbf rate 100mbit latency "$LATENCY" burst "$BURST"
      done
      echo "Baseline applied: 100mbit rate limit, no delay, no loss"
      ;;
  1) apply 100   5  1  ; echo "Case 1 applied: RTT 10ms, 1% loss, 100mbit"  ;;
  2) apply 100 100 20  ; echo "Case 2 applied: RTT 200ms, 20% loss, 100mbit" ;;
  3) apply  80 100 ""  ; echo "Case 3 applied: RTT 200ms, no loss, 80mbit"   ;;
  clear) clear_qdisc   ; echo "Cleared."                                     ;;
  show)  show_qdisc    ; exit 0                                              ;;
  *) usage; exit 2 ;;
esac

echo
show_qdisc

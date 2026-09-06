#!/usr/bin/env bash
set -euo pipefail

# Run on the SERVER and CLIENT Ubuntu VMs with sudo.
# Handout: both endpoints are rate limited to 100mbit egress in all three cases.

DEV="${DEV:-ens33}"
RATE="${RATE:-100}"
BURST="${BURST:-9015}"
LATENCY="${LATENCY:-0.001ms}"

case "${1:-apply}" in
  apply)
    tc qdisc del dev "$DEV" root 2>/dev/null || true
    tc qdisc add dev "$DEV" root tbf rate "${RATE}mbit" latency "$LATENCY" burst "$BURST"
    echo "Shaped $DEV to ${RATE}mbit."
    ;;
  clear)
    tc qdisc del dev "$DEV" root 2>/dev/null || true
    echo "Cleared $DEV."
    ;;
  *)
    echo "Usage: sudo DEV=ens33 ./node-shape.sh apply|clear"; exit 2 ;;
esac
tc qdisc show dev "$DEV"

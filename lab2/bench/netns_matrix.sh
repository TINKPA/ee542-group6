#!/bin/bash
# EE542 Lab2 — sweep every method across the 3 cases in the netns testbed.
# Run INSIDE the Ubuntu VM. Assumes $HOME/ftr (built from ../src) and
# $HOME/data.bin (1 GiB) exist. Results append to $HOME/runs_netns.jsonl,
# one line per run tagged with its method.
#
#   nak       : the paper protocol, 3 reps (matches the report's headline table)
#   carousel  : blind-loop baseline, 1 rep (the gap is the point, not variance)
#   ack       : per-packet-ACK baseline, 1 rep
#   stopwait  : window=1, 1 rep on a SMALL file — it cannot finish 1 GiB on a
#               lossy/high-RTT case in bounded time; take its steady rate and
#               extrapolate in the writeup.
#
# Usage: netns_matrix.sh [mtu] [nak_reps]     (defaults: 1500, 3)
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
NL="$DIR/netns_lab.sh"
MTU=${1:-1500}
NAK_REPS=${2:-3}
H="$HOME"
SMALL="$H/small.bin"

[ -x "$H/ftr" ] || { echo "missing $H/ftr — build ../src and copy it here"; exit 1; }
[ -f "$H/data.bin" ] || { echo "missing $H/data.bin (1 GiB test file)"; exit 1; }
[ -f "$SMALL" ] || { echo "creating 32MB small.bin for stopwait"; head -c 33554432 /dev/urandom > "$SMALL"; }

sudo bash "$NL" setup "$MTU"
for C in 1 2 3; do
  # sender pacing target, kept just under each case's link rate so we do not
  # feed the router tbf above its cap (which would add shaper-drop retransmits)
  case $C in 1) RATE=97;; 2) RATE=97;; 3) RATE=77;; esac
  sudo bash "$NL" case "$C"
  echo "== case $C : verify =="; sudo bash "$NL" verify
  for r in $(seq 1 "$NAK_REPS"); do
    sudo bash "$NL" run "c${C}_nak_m${MTU}_r${r}" "$RATE" "$MTU" nak
  done
  sudo bash "$NL" run "c${C}_carousel_m${MTU}_r1" "$RATE" "$MTU" carousel
  sudo bash "$NL" run "c${C}_ack_m${MTU}_r1"      "$RATE" "$MTU" ack
  sudo bash "$NL" run "c${C}_stopwait_m${MTU}_r1" "$RATE" "$MTU" stopwait "$SMALL"
done
sudo bash "$NL" teardown
echo "DONE -> $H/runs_netns.jsonl"

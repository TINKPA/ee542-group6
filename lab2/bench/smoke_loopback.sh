#!/bin/bash
# EE542 Lab2 — loopback correctness smoke test for every method.
# Verifies each method delivers a byte-exact file over 127.0.0.1, exercising
# the retransmit path via the receiver's --drop loss simulation. This checks
# CORRECTNESS ONLY (MD5); throughput/latency require the netns or VM testbed.
#
# Usage: smoke_loopback.sh [ftr_binary]   (default: ../src/ftr)
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
FTR="${1:-$DIR/../src/ftr}"
WORK="$(mktemp -d)"
trap 'pkill -x ftr 2>/dev/null; rm -rf "$WORK"' EXIT
PASS=0; FAIL=0

run() {  # run <name> <method> <size_bytes> <drop> <mtu>
  local name=$1 method=$2 size=$3 drop=$4 mtu=$5
  local port=$((9000 + RANDOM % 500))
  local in="$WORK/in_$name.bin" out="$WORK/out_$name.bin"
  head -c "$size" /dev/urandom > "$in"
  local md5in; md5in=$(md5 -q "$in" 2>/dev/null || md5sum "$in" | awk '{print $1}')
  pkill -x ftr 2>/dev/null; sleep 0.2
  "$FTR" recv "$out" --port "$port" --drop "$drop" > "$WORK/recv_$name.log" 2>&1 &
  sleep 0.4
  "$FTR" send "$in" 127.0.0.1 --method "$method" --port "$port" --mtu "$mtu" \
      > "$WORK/send_$name.log" 2>&1
  local src=$?
  for _ in $(seq 1 50); do [ -s "$out" ] && break; sleep 0.2; done
  sleep 0.5; pkill -x ftr 2>/dev/null
  local md5out; md5out=$(md5 -q "$out" 2>/dev/null || md5sum "$out" 2>/dev/null | awk '{print $1}')
  local rounds pkts; rounds=$(grep '^ROUNDS' "$WORK/send_$name.log" | awk '{print $2}')
  pkts=$(grep '^TOTAL_PKTS' "$WORK/send_$name.log" | awk '{print $2}')
  if [ -n "$md5out" ] && [ "$md5in" = "$md5out" ]; then
    printf 'PASS  %-22s method=%-9s size=%-9s drop=%-4s rounds=%-3s pkts=%s\n' \
      "$name" "$method" "$size" "$drop" "${rounds:-?}" "${pkts:-?}"; PASS=$((PASS+1))
  else
    printf 'FAIL  %-22s method=%-9s size=%-9s drop=%-4s (send rc=%s, in=%s out=%s)\n' \
      "$name" "$method" "$size" "$drop" "$src" "$md5in" "${md5out:-none}"; FAIL=$((FAIL+1))
    echo "  --- send log tail ---"; tail -4 "$WORK/send_$name.log" | sed 's/^/  /'
    echo "  --- recv log tail ---"; tail -4 "$WORK/recv_$name.log" | sed 's/^/  /'
  fi
}

echo "== ftr = $FTR =="
run nak_clean       nak      16777216 0.0  1500
run nak_loss20      nak      16777216 0.2  1500
run carousel_clean  carousel 16777216 0.0  1500
run carousel_loss20 carousel 16777216 0.2  1500
run ack_clean       ack      16777216 0.0  1500
run ack_loss20      ack      16777216 0.2  1500
run stopwait_clean  stopwait  8388608 0.0  1500
run stopwait_loss   stopwait   262144 0.15 1500   # tiny: 1s RTO makes loss slow
run nak_mtu9000     nak      16777216 0.1  9000
echo "== $PASS passed, $FAIL failed =="
[ "$FAIL" -eq 0 ]

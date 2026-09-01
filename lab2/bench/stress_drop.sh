#!/bin/bash
# Loop short transfers under simulated loss to confirm the protocol always
# converges and passes md5. Correctness stress, not a throughput measurement.
set -u
FTR="${1:-./ftr}"; N="${2:-20}"; DROP="${3:-0.2}"
pass=0
for i in $(seq 1 "$N"); do
  port=$((9000 + RANDOM % 500))
  head -c 16777216 /dev/urandom > /tmp/in.bin
  "$FTR" recv /tmp/out.bin --port "$port" --drop "$DROP" >/dev/null 2>&1 &
  sleep 0.3
  "$FTR" send /tmp/in.bin 127.0.0.1 --port "$port" >/dev/null 2>&1
  sleep 0.3; pkill -x ftr 2>/dev/null
  [ "$(md5 -q /tmp/in.bin)" = "$(md5 -q /tmp/out.bin)" ] && pass=$((pass+1))
done
echo "$pass/$N passed at drop=$DROP"

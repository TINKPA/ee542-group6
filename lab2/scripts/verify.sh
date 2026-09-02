#!/usr/bin/env bash
set -uo pipefail

# Run on an ENDPOINT (server or client). Verifies the bench actually matches
# the case you think you applied, and saves raw evidence for the report.
#
#   PEER=192.168.10.100 ./verify.sh 2
#
# Exits nonzero if any assertion fails. Never record a transfer number from a
# bench that did not pass this first.
#
# Handout tolerances:
#   loss  within +-20% of the configured value
#   delay slightly greater than configured
#   rate  near the configured cap

PEER="${PEER:-}"
CASE="${1:-}"
IPERF="${IPERF:-iperf3}"
OUT="${OUT:-$HOME/lab2-results}"

if [ -z "$PEER" ] || [ -z "$CASE" ]; then
  echo "Usage: PEER=<peer_ip> ./verify.sh 1|2|3"; exit 2
fi

case "$CASE" in
  1) EXP_RTT=10;  EXP_LOSS=1;  EXP_RATE=100 ;;
  2) EXP_RTT=200; EXP_LOSS=20; EXP_RATE=100 ;;
  3) EXP_RTT=200; EXP_LOSS=0;  EXP_RATE=80  ;;
  *) echo "Case must be 1, 2 or 3"; exit 2 ;;
esac

STAMP="$(date +%Y%m%d-%H%M%S)"
DIR="$OUT/case${CASE}-${STAMP}"
mkdir -p "$DIR"
FAIL=0

note() { printf '%-34s %s\n' "$1" "$2"; }
fail() { printf '  FAIL  %s\n' "$1"; FAIL=1; }
pass() { printf '  ok    %s\n' "$1"; }

echo "=== Lab 2 bench verification: Case $CASE -> $PEER ==="
echo "Raw output: $DIR"
echo

# ---------------------------------------------------------------- ping
echo "[1/3] ping -i 0.2 -c 200 (this takes ~40s)"
ping -i 0.2 -c 200 "$PEER" > "$DIR/ping.txt" 2>&1 || true

RTT=$(awk -F'/' '/rtt|round-trip/ {print $5}' "$DIR/ping.txt")
LOSS=$(grep -o '[0-9.]*% packet loss' "$DIR/ping.txt" | grep -o '[0-9.]*')

if [ -z "$RTT" ] || [ -z "$LOSS" ]; then
  fail "could not parse ping output (peer unreachable?)"
else
  note "measured RTT" "${RTT} ms (expect >= ${EXP_RTT})"
  note "measured loss" "${LOSS}% (expect ~${EXP_LOSS}%)"

  awk -v r="$RTT" -v e="$EXP_RTT" 'BEGIN{exit !(r >= e && r <= e*1.5)}' \
    && pass "RTT slightly above configured" \
    || fail "RTT ${RTT}ms outside [${EXP_RTT}, $(awk -v e=$EXP_RTT 'BEGIN{print e*1.5}')]"

  if [ "$EXP_LOSS" = "0" ]; then
    awk -v l="$LOSS" 'BEGIN{exit !(l <= 0.5)}' \
      && pass "no packet loss" \
      || fail "expected no loss, measured ${LOSS}%"
  else
    awk -v l="$LOSS" -v e="$EXP_LOSS" 'BEGIN{exit !(l >= e*0.8 && l <= e*1.2)}' \
      && pass "loss within +-20% of configured" \
      || fail "loss ${LOSS}% outside +-20% of ${EXP_LOSS}%"
  fi
fi
echo

# ---------------------------------------------------------------- UDP
echo "[2/3] $IPERF UDP"
$IPERF -c "$PEER" -u -b 100M -t 10 -J > "$DIR/iperf-udp.json" 2>"$DIR/iperf-udp.err" || true

read -r UMBPS ULOSS <<<"$(python3 - "$DIR/iperf-udp.json" <<'PY' 2>/dev/null
import json,sys
try:
    s=json.load(open(sys.argv[1]))["end"]["sum"]
    print(round(s["bits_per_second"]/1e6,1), round(s.get("lost_percent",0),2))
except Exception:
    print("", "")
PY
)"

if [ -z "$UMBPS" ]; then
  fail "could not parse UDP iperf (is $IPERF -s running on $PEER?)"
else
  note "UDP throughput" "${UMBPS} Mbps"
  note "UDP loss" "${ULOSS}%"
  awk -v m="$UMBPS" -v e="$EXP_RATE" 'BEGIN{exit !(m >= e*0.7)}' \
    && pass "UDP near the configured cap" \
    || fail "UDP ${UMBPS} Mbps well under ${EXP_RATE} Mbps cap"
fi
echo

# ---------------------------------------------------------------- TCP
echo "[3/3] $IPERF TCP"
$IPERF -c "$PEER" -t 10 -J > "$DIR/iperf-tcp.json" 2>"$DIR/iperf-tcp.err" || true

TMBPS=$(python3 - "$DIR/iperf-tcp.json" <<'PY' 2>/dev/null
import json,sys
try:
    print(round(json.load(open(sys.argv[1]))["end"]["sum_received"]["bits_per_second"]/1e6,1))
except Exception:
    print("")
PY
)

if [ -z "$TMBPS" ]; then
  fail "could not parse TCP iperf"
else
  note "TCP throughput" "${TMBPS} Mbps"
  pass "recorded (this is the number your protocol must beat)"
fi

# ---------------------------------------------------------------- summary
{
  echo "case=$CASE peer=$PEER stamp=$STAMP"
  echo "rtt_ms=$RTT loss_pct=$LOSS udp_mbps=$UMBPS udp_loss_pct=$ULOSS tcp_mbps=$TMBPS"
} | tee "$DIR/summary.txt"

echo
if [ "$FAIL" -eq 0 ]; then
  echo "PASS - bench matches Case $CASE. Safe to record transfer numbers."
else
  echo "FAIL - do NOT record transfer numbers until this passes."
fi
exit "$FAIL"

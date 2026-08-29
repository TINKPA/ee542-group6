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
EXP_RT_LOSS=$(awk -v p="$EXP_LOSS" 'BEGIN{printf "%.2f", (1-(1-p/100)^2)*100}')

PINGS=200
read -r LOSS_LO LOSS_HI <<<"$(awk -v e="$EXP_RT_LOSS" -v n="$PINGS" 'BEGIN{
  p = e/100
  sd = 100*sqrt(p*(1-p)/n)
  m  = (0.2*e > 2.5*sd) ? 0.2*e : 2.5*sd
  lo = e - m; if (lo < 0.3*e) lo = 0.3*e
  printf "%.2f %.2f", lo, e + m
}')"

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
  note "measured loss" "${LOSS}% (round trip; expect ~${EXP_RT_LOSS}%)"
  note "configured per direction" "${EXP_LOSS}% on each router interface"
  note "acceptance band" "${LOSS_LO}% .. ${LOSS_HI}% (n=${PINGS})"

  awk -v r="$RTT" -v e="$EXP_RTT" 'BEGIN{exit !(r >= e && r <= e*1.5)}' \
    && pass "RTT slightly above configured" \
    || fail "RTT ${RTT}ms outside [${EXP_RTT}, $(awk -v e=$EXP_RTT 'BEGIN{print e*1.5}')]"

  if [ "$EXP_LOSS" = "0" ]; then
    awk -v l="$LOSS" 'BEGIN{exit !(l <= 0.5)}' \
      && pass "no packet loss" \
      || fail "expected no loss, measured ${LOSS}%"
  else
    awk -v l="$LOSS" -v lo="$LOSS_LO" -v hi="$LOSS_HI" 'BEGIN{exit !(l >= lo && l <= hi)}' \
      && pass "loss consistent with ${EXP_RT_LOSS}% expected round trip" \
      || fail "loss ${LOSS}% outside ${LOSS_LO}%..${LOSS_HI}%"
  fi
fi
echo

# ---------------------------------------------------------------- UDP
echo "[2/3] UDP throughput and loss"
# iperf3 carries a TCP control connection for setup and for returning the
# receiver's stats. Under Case 2 (36% round-trip loss, 200ms RTT) that control
# channel times out and no summary comes back, even though the UDP data flowed
# fine. The handout specifies iperf version 2, which has no such dependency, so
# prefer iperf2 when installed and fall back to iperf3 otherwise.
UMBPS=""; ULOSS=""
if command -v iperf >/dev/null 2>&1; then
  echo "      using iperf2 (robust under heavy loss)"
  iperf -u -c "$PEER" -b 100m -t 10 > "$DIR/iperf2-udp.txt" 2>&1 || true
  # Parse ONLY the "Server Report" block: that is what actually ARRIVED.
  # The client's own summary line reports what it SENT, which is not
  # throughput and must never be reported as such.
  read -r UMBPS ULOSS <<<"$(awk '
    /Server Report:/ { sr=1 }
    sr {
      for (i=1;i<=NF;i++) {
        if      ($i=="Mbits/sec") mb=$(i-1)
        else if ($i=="Kbits/sec") mb=$(i-1)/1000
        if ($i ~ /^\([0-9.]+%\)$/) { g=$i; gsub(/[()%]/,"",g); ls=g }
      }
    }
    END { if (mb!="") printf "%s %s", mb, (ls==""?"0":ls) }
  ' "$DIR/iperf2-udp.txt")"
  if [ -z "$UMBPS" ] && grep -q "did not receive ack" "$DIR/iperf2-udp.txt" 2>/dev/null; then
    echo "      no Server Report: iperf2 got no ack for its final datagram."
    echo "      Usually means the netem queue is deep enough to delay it past"
    echo "      the retry window - check NETEM_LIMIT on the router."
  fi
fi
if [ -z "$UMBPS" ]; then
  echo "      using iperf3"
  $IPERF -c "$PEER" -u -b 100M -t 10 -J > "$DIR/iperf-udp.json" 2>"$DIR/iperf-udp.err" || true
  UMBPS=$(grep -o '"bits_per_second":[[:space:]]*[0-9.]*' "$DIR/iperf-udp.json" 2>/dev/null | tail -1 | grep -o '[0-9.]*$' | awk '{printf "%.1f", $1/1e6}')
  ULOSS=$(grep -o '"lost_percent":[[:space:]]*[0-9.-]*' "$DIR/iperf-udp.json" 2>/dev/null | tail -1 | grep -o '[0-9.-]*$')
fi
if [ -z "$UMBPS" ]; then
  fail "could not parse UDP iperf (is $IPERF -s running on $PEER?)"
else
  note "UDP throughput" "${UMBPS} Mbps"
  note "UDP loss" "${ULOSS}%"
  # Expected arrival rate: 100mbit is offered, the router caps at EXP_RATE,
  # and EXP_LOSS is dropped per direction on the one-way path.
  EXP_UDP=$(awk -v cap="$EXP_RATE" -v l="$EXP_LOSS" 'BEGIN{
    o = (100 < cap) ? 100 : cap
    printf "%.1f", o * (1 - l/100)
  }')
  note "UDP expected" "~${EXP_UDP} Mbps (offer 100, cap ${EXP_RATE}, ${EXP_LOSS}% one-way)"
  # Bound BOTH sides. Too high matters: reading the sender's rate instead of
  # the receiver's, or a shaper that is not actually enforcing its cap, both
  # show up as a number above the ceiling.
  awk -v m="$UMBPS" -v e="$EXP_UDP" 'BEGIN{exit !(m >= e*0.8 && m <= e*1.2)}' \
    && pass "UDP within +-20% of expected ${EXP_UDP} Mbps" \
    || fail "UDP ${UMBPS} Mbps outside +-20% of expected ${EXP_UDP} Mbps"
fi
echo

# ---------------------------------------------------------------- TCP
echo "[3/3] TCP throughput"
# Same iperf3 control-channel fragility as the UDP leg: under Case 2 the TCP
# control connection often fails to return statistics even though the transfer
# ran. Prefer iperf2, which reports send-side stats locally.
TMBPS=""
if command -v iperf >/dev/null 2>&1; then
  echo "      using iperf2"
  iperf -c "$PEER" -t 10 > "$DIR/iperf2-tcp.txt" 2>&1 || true
  TMBPS=$(awk '{
      for (i=1;i<=NF;i++) {
        if      ($i=="Mbits/sec") mb=$(i-1)
        else if ($i=="Kbits/sec") mb=$(i-1)/1000
        else if ($i=="bits/sec")  mb=$(i-1)/1000000
      }
    } END { if (mb!="") printf "%.2f", mb }' "$DIR/iperf2-tcp.txt")
fi
if [ -z "$TMBPS" ]; then
  echo "      using iperf3"
  $IPERF -c "$PEER" -t 10 -J > "$DIR/iperf-tcp.json" 2>"$DIR/iperf-tcp.err" || true
  TMBPS=$(grep -o '"bits_per_second":[[:space:]]*[0-9.]*' "$DIR/iperf-tcp.json" 2>/dev/null | tail -1 | grep -o '[0-9.]*$' | awk '{printf "%.2f", $1/1000000}')
fi
if [ -z "$TMBPS" ]; then
  fail "could not parse TCP iperf"
else
  note "TCP throughput" "${TMBPS} Mbps"
  pass "recorded (this is the number your protocol must beat)"
fi

# ---------------------------------------------------------------- summary
{
  echo "case=$CASE peer=$PEER stamp=$STAMP"
  echo "cfg_loss_per_dir_pct=$EXP_LOSS expected_rt_loss_pct=$EXP_RT_LOSS"
  echo "rtt_ms=$RTT loss_pct=$LOSS udp_mbps=$UMBPS udp_loss_pct=$ULOSS tcp_mbps=$TMBPS"
} | tee "$DIR/summary.txt"

echo
if [ "$FAIL" -eq 0 ]; then
  echo "PASS - bench matches Case $CASE. Safe to record transfer numbers."
else
  echo "FAIL - do NOT record transfer numbers until this passes."
fi
exit "$FAIL"

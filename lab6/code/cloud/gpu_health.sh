#!/usr/bin/env bash
# EE542 Lab 6: is this pod's GPU actually healthy? Run before any measurement.
# Pod 4 (y9p54up2fblahv, 2026-10-02) had its L4 stuck at 210 MHz with the
# hardware power brake asserted; every kernel ran 6-7x slow and every copy
# 10x slow, with nothing in our code to blame. nvidia-smi shows it:
#   clocks_event_reasons.active 0x88 = HW_SLOWDOWN | HW_POWER_BRAKE.
# This script prints the clock/throttle state and times one cublas N=2048
# multiply, which should be ~1.0 ms on a healthy L4. Exits 1 if it is > 2 ms
# or if a hardware throttle reason is active.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v nvcc >/dev/null || export PATH="/usr/local/cuda/bin:$PATH"
echo "## throttle state (idle)"
nvidia-smi --query-gpu=name,clocks.sm,clocks.max.sm,power.draw,power.limit,pstate,clocks_throttle_reasons.active,clocks_throttle_reasons.hw_slowdown,clocks_throttle_reasons.hw_power_brake_slowdown,clocks_throttle_reasons.sw_thermal_slowdown --format=csv
make -s -C "$here/../part6" matrix_cublas 2>&1 | grep -v 'nvcc warning' || true
echo "## cublas N=2048 (healthy L4: kernel_ms ~1.0, h2d_ms ~3, init_ms ~200)"
line="$("$here/../part6/matrix_cublas" 2048 | grep '^wall=')"; echo "$line"
k="$(sed -E 's/.*kernel_ms=([0-9.]+).*/\1/' <<<"$line")"
hw="$(nvidia-smi --query-gpu=clocks_throttle_reasons.hw_slowdown --format=csv,noheader)"
if [ "$hw" != "Not Active" ] || awk "BEGIN{exit !($k > 2.0)}"; then
  echo "UNHEALTHY: hw_slowdown=$hw kernel_ms=$k -> terminate this pod and provision another"; exit 1
fi
echo "HEALTHY: kernel_ms=$k"

#!/bin/bash
# Restage AWS §1 iperf results into the filename layout the ORIGINAL plot_sec1_v4.py
# expects, so that script is reused byte-for-byte (only its RAW dir is repointed).
# Original expects:  <DST>/sec1_c<C>_<proto>_<c2s|s2c>[_m9000].txt   (9000 suffix = jumbo)
# We have:           results/sec1_c<C>_m<MTU>/<tcp|udp>_<c2s|s2c>.txt
# MTU 9001 is staged under the script's "_m9000" suffix (its jumbo panel).
# Usage: aws_sec1_stage.sh   ->  ../../data/raw/aws/sec1_iperf/
set -eu
DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$DIR/results"
DST="$DIR/../../data/raw/aws/sec1_iperf"
mkdir -p "$DST"
for C in 0 1 2 3; do
  for MTU in 1500 9001; do
    suf=""; [ "$MTU" = 9001 ] && suf="_m9001"
    for proto in tcp udp; do
      for d in c2s s2c; do
        s="$SRC/sec1_c${C}_m${MTU}/${proto}_${d}.txt"
        [ -f "$s" ] && cp "$s" "$DST/sec1_c${C}_${proto}_${d}${suf}.txt"
      done
    done
  done
done
echo "staged -> $DST"; ls "$DST" | wc -l

#!/usr/bin/env bash
# EE542 Lab 8: re-run only the measurements (Part 2.4 bench, Part 5 classify)
# after code changes; engines and PCAPs from run_part2_5.sh are reused.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. ~/venv/bin/activate
raw="$here/../../data/raw"; work="$here/../../data/work"; host="$(hostname -s)"
cd "$work"
python3 "$here/../part2/bench.py" --csv "$raw/part2_$host.csv" 2>&1 | tee "$raw/part2_$host.log"
python3 "$here/../part5/classify.py" --rx rx_images_shuf.bin --orig frames_orig.bin \
  --labels labels.json --engine resnet18_fp16.engine --csv "$raw/part5_$host.csv" 2>&1 | tee "$raw/part5_$host.log"

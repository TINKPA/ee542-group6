#!/usr/bin/env bash
# EE542 Lab 8: Parts 1.3 -> 5 on the GPU box, in order. Detach-safe:
#   nohup ./run_part2_5.sh > ../../data/raw/run25.log 2>&1 < /dev/null &
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. ~/venv/bin/activate
export PATH=/usr/local/cuda-12.6/bin:$PATH
raw="$here/../../data/raw"; work="$here/../../data/work"; mkdir -p "$raw" "$work"
host="$(hostname -s)"
echo "=== Part 1.3 check"; "$here/../part1/check.sh"
cd "$work"
echo "=== Part 2.1 export";  python3 "$here/../part2/export_onnx.py" || exit 1
ls -la resnet18_*.onnx*
echo "=== Part 2.2 build"
python3 "$here/../part2/build_engine.py" resnet18_fp32.onnx resnet18_fp32.engine || exit 1
python3 "$here/../part2/build_engine.py" resnet18_fp16.onnx resnet18_fp16.engine || exit 1
echo "=== Part 2.4 bench"
python3 "$here/../part2/bench.py" --csv "$raw/part2_$host.csv" | tee "$raw/part2_$host.log"
echo "=== Parts 3+4"; "$here/../part4/run_rx.sh"
echo "=== Part 5"
python3 "$here/../part5/classify.py" --rx rx_images_shuf.bin --orig frames_orig.bin \
  --labels labels.json --engine resnet18_fp16.engine --csv "$raw/part5_$host.csv" | tee "$raw/part5_$host.log"
cp labels.json "$raw/"
echo "ALL DONE"

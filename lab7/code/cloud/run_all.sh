#!/usr/bin/env bash
# EE542 Lab 7: the whole measurement campaign on one cloud GPU pod.
# Launch detached from the lab7/ directory copied to the pod:
#   nohup bash code/cloud/run_all.sh > run_all.log 2>&1 < /dev/null &
# Stages run one at a time so CPU jobs never share the box with GPU jobs.
# Data set lives on the container disk ($DS, default /root/ds/catsdogs): the
# /workspace network volume extracted at ~2 MB/s and would also throttle the
# DataLoader timings.
# Results: data/raw/*_<host>.{csv,log}. Ends with the line DONE.
# The 2026-10-18 run (pod rll551f5fxpv81) ran stages env..part3, then
# STAGES=ablation, then the cpu5 commands by hand, in that order.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lab="$(cd "$here/../.." && pwd)"
raw="$lab/data/raw"; mkdir -p "$raw"
host="$(hostname -s)"
DS="${DS:-/root/ds/catsdogs}"
W="${WORKERS:-4}"
STAGES="${STAGES:-env health data part1 part2 part3 ablation cpu5}"
has() { [[ " $STAGES " == *" $1 "* ]]; }
stamp() { echo "=== $(date -u +%H:%M:%S) $*"; }

python3 -c "import PIL, torchvision, matplotlib" 2>/dev/null || pip install -q pillow torchvision matplotlib

has env    && { stamp env;    bash "$here/env_probe.sh" > /dev/null; }
has health && { stamp health; bash "$here/gpu_health.sh" | tee "$raw/health_$host.log"; }
if has data; then
  stamp data
  mkdir -p "$(dirname "$DS")"
  ( cd "$(dirname "$DS")" && python3 "$lab/code/dataset/prepare_catsdogs.py" \
      --zip "$(dirname "$DS")/kagglecatsanddogs_5340.zip" --out "$DS" ) | tee "$raw/data_$host.log"
fi
if has part1; then
  stamp "part1 (numpy MLP examples on the pod CPU)"
  ( cd "$lab/code/part1" && python3 run_examples.py --no-plot ) | tee "$raw/part1_$host.log"
fi
if has part2; then
  P2="$lab/code/part2/numpy_cnn.py"; CSV="$raw/part2_$host.csv"; CACHE="$DS/pixels64.npz"
  stamp "part2 loop conv, from JPEG, + one faithful epoch"
  python3 "$P2" --data "$DS" --conv loop --seed 0 --cache "$CACHE" --faithful-epochs 1 --csv "$CSV" \
    | tee "$raw/part2_loop_s0_$host.log"
  for b0 in 0 0.5; do for s in 0 1 2; do
    stamp "part2 vec conv b0=$b0 seed=$s"
    python3 "$P2" --data "$DS" --conv vec --seed $s --b0 $b0 --cache "$CACHE" --csv "$CSV" \
      | tee "$raw/part2_vec_b${b0}_s${s}_$host.log"
  done; done
fi
if has part3; then
  P3="$lab/code/part3/torch_cnn.py"; CSV="$raw/part3_$host.csv"
  for s in 0 1 2; do
    for p in loader preload; do
      stamp "part3 catdog cuda $p seed=$s"
      python3 "$P3" --data "$DS" --model catdog --device cuda --pipeline $p --workers $W --seed $s --csv "$CSV" \
        | tee "$raw/part3_catdog_cuda_${p}_s${s}_$host.log"
    done
  done
  stamp "part3 tiny (numpy model) cuda preload"
  python3 "$P3" --data "$DS" --model tiny --device cuda --pipeline preload --workers $W --seed 0 --csv "$CSV" \
    | tee "$raw/part3_tiny_cuda_preload_s0_$host.log"
  stamp "part3 tiny cpu preload"
  python3 "$P3" --data "$DS" --model tiny --device cpu --pipeline preload --workers $W --seed 0 --csv "$CSV" \
    | tee "$raw/part3_tiny_cpu_preload_s0_$host.log"
  stamp "part3 catdog cpu preload"
  python3 "$P3" --data "$DS" --model catdog --device cpu --pipeline preload --workers $W --seed 0 --csv "$CSV" \
    | tee "$raw/part3_catdog_cpu_preload_s0_$host.log"
  stamp "part3 catdog cpu loader"
  python3 "$P3" --data "$DS" --model catdog --device cpu --pipeline loader --workers $W --seed 0 --csv "$CSV" \
    | tee "$raw/part3_catdog_cpu_loader_s0_$host.log"
fi
if has ablation; then
  # output-activation ablation: the tutorial's ReLU output vs a linear output
  for s in 0 1 2; do
    stamp "ablation catdog cuda preload head=linear seed=$s"
    python3 "$lab/code/part3/torch_cnn.py" --data "$DS" --model catdog --device cuda --pipeline preload \
      --head linear --workers $W --seed $s --csv "$raw/part3_$host.csv" \
      | tee "$raw/part3_catdog_cuda_preload_linear_s${s}_$host.log"
    stamp "ablation numpy vec head=linear seed=$s"
    python3 "$lab/code/part2/numpy_cnn.py" --data "$DS" --conv vec --head linear --seed $s \
      --cache "$DS/pixels64.npz" --csv "$raw/part2_$host.csv" | tee "$raw/part2_vec_linear_s${s}_$host.log"
  done
fi
if has cpu5; then
  # The container is allowed 5.1 cores but torch starts 24 threads; the default
  # CPU runs above are oversubscribed. These are the CPU rows the report uses.
  P3="$lab/code/part3/torch_cnn.py"; CSV="$raw/part3_$host.csv"
  stamp "cpu5 catdog cpu preload threads=5 seed=1"
  python3 "$P3" --data "$DS" --model catdog --device cpu --pipeline preload --threads 5 --workers $W --seed 1 \
    --csv "$CSV" > "$raw/part3_catdog_cpu_preload_t5_s1_$host.log" 2>&1
  stamp "cpu5 tiny cpu preload threads=5 seed=0"
  python3 "$P3" --data "$DS" --model tiny --device cpu --pipeline preload --threads 5 --workers $W --seed 0 \
    --csv "$CSV" > "$raw/part3_tiny_cpu_preload_t5_s0_$host.log" 2>&1
  stamp "cpu5 catdog cpu loader threads=5 seed=1"
  python3 "$P3" --data "$DS" --model catdog --device cpu --pipeline loader --threads 5 --workers $W --seed 1 \
    --csv "$CSV" > "$raw/part3_catdog_cpu_loader_t5_s1_$host.log" 2>&1
fi
bash "$here/gpu_health.sh" | tee -a "$raw/health_$host.log" || true
stamp DONE
echo DONE

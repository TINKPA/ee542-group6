#!/usr/bin/env bash
# EE542 Lab 6: on the cloud GPU box, probe the environment, then run the CPU
# sweep (Part 1, re-measured here so Part 5's speedup is same-machine) and the
# naive GPU sweep (Part 2/3) over the same N list. Detach-safe: run under nohup.
#   nohup ./run_part1_part2.sh > run.log 2>&1 &
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Container images keep nvcc in /usr/local/cuda/bin, which a non-login shell lacks.
command -v nvcc >/dev/null || export PATH="/usr/local/cuda/bin:$PATH"
SIZES=(${SIZES:-256 512 768 1024 1536 2048 3072})
"$here/env_probe.sh"
"$here/gpu_health.sh"
echo "=== CPU sweep"; "$here/../part1/sweep_cpu.sh" "${SIZES[@]}"
echo "=== naive GPU sweep"; "$here/../part2/sweep_gpu.sh" "${SIZES[@]}"
echo "DONE"

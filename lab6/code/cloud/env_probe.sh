#!/usr/bin/env bash
# EE542 Lab 6: record the machine every cloud measurement was taken on.
# Run once per pod; output goes next to the CSVs so the report's Setup
# paragraph can quote it. Paths relative to this script.
#   ./env_probe.sh            -> data/raw/env_<host>.txt
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v nvcc >/dev/null || export PATH="/usr/local/cuda/bin:$PATH"
OUT="${OUT:-$here/../../data/raw/env_$(hostname -s).txt}"
mkdir -p "$(dirname "$OUT")"
{
  echo "# probed $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(hostname)"
  echo "## os";        . /etc/os-release 2>/dev/null && echo "$PRETTY_NAME"; uname -r -m
  echo "## cpu";       lscpu | grep -E 'Model name|^CPU\(s\)|Thread|Core|Socket|L2|L3|NUMA node\(s\)'
  echo "## mem";       grep MemTotal /proc/meminfo
  echo "## cgroup cpu quota (container share)"; cat /sys/fs/cgroup/cpu.max 2>/dev/null || { echo -n "cfs_quota_us/period_us: "; cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us /sys/fs/cgroup/cpu/cpu.cfs_period_us 2>/dev/null | paste -sd/ - || echo n/a; }
  echo "## gpu";       nvidia-smi --query-gpu=name,driver_version,memory.total,pcie.link.gen.max,pcie.link.gen.current,pcie.link.width.max,pcie.link.width.current,clocks.max.sm,clocks.max.memory --format=csv
  echo "## nvcc";      nvcc --version | tail -2
  echo "## gcc";       gcc --version | head -1
  echo "## nvidia-smi"; nvidia-smi
} > "$OUT" 2>&1
cat "$OUT"

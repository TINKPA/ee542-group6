#!/usr/bin/env bash
# EE542 Lab 7: record the machine every measurement was taken on (adapted
# from Lab 6; no nvcc here, adds the Python stack instead).
#   ./env_probe.sh  -> data/raw/env_<host>.txt
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${OUT:-$here/../../data/raw/env_$(hostname -s).txt}"
mkdir -p "$(dirname "$OUT")"
{
  echo "# probed $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(hostname)"
  echo "## os";   . /etc/os-release 2>/dev/null && echo "$PRETTY_NAME"; uname -r -m
  echo "## cpu";  lscpu | grep -E 'Model name|^CPU\(s\)|Thread|Core|Socket|L2|L3'
  echo "## mem";  grep MemTotal /proc/meminfo
  echo "## cgroup cpu quota (container share)"; cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo n/a
  echo "## nproc"; nproc
  echo "## gpu";  nvidia-smi --query-gpu=name,driver_version,memory.total,pcie.link.gen.max,pcie.link.width.max,clocks.max.sm --format=csv
  echo "## python"; python3 -c "import sys,numpy,torch,torchvision,PIL;print(sys.version.split()[0],'numpy',numpy.__version__,'torch',torch.__version__,'torchvision',torchvision.__version__,'PIL',PIL.__version__,'cuda',torch.version.cuda,'cudnn',torch.backends.cudnn.version())"
  echo "## nvidia-smi"; nvidia-smi
} > "$OUT" 2>&1
cat "$OUT"

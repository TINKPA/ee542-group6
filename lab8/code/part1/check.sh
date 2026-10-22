#!/usr/bin/env bash
# EE542 Lab 8 Part 1 (Step 1.3): record GPU, driver, CUDA, PyTorch, TensorRT,
# DPDK versions. Output also saved to data/raw/env_<host>.txt.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH=/usr/local/cuda-12.6/bin:$PATH
. ~/venv/bin/activate
OUT="$here/../../data/raw/env_$(hostname -s).txt"
mkdir -p "$(dirname "$OUT")"
{
  echo "# probed $(date -u +%Y-%m-%dT%H:%M:%SZ) on $(hostname)"
  echo "## os";  . /etc/os-release && echo "$PRETTY_NAME"; uname -r -m
  echo "## cpu"; lscpu | grep -E 'Model name|^CPU\(s\)'; grep MemTotal /proc/meminfo
  echo "## nvidia-smi"; nvidia-smi
  nvidia-smi --query-gpu=name,driver_version,memory.total,pci.bus_id,pcie.link.gen.current,pcie.link.width.current --format=csv
  echo "## nvcc"; nvcc --version
  echo "## torch"; python3 -c "import torch; print(torch.__version__, 'cuda', torch.version.cuda, 'available', torch.cuda.is_available())"
  echo "## torchvision"; python3 -c "import torchvision; print(torchvision.__version__)"
  echo "## tensorrt"; python3 -c "import tensorrt; print(tensorrt.__version__)"
  echo "## onnx"; python3 -c "import onnx; print(onnx.__version__)"
  echo "## dpdk"; pkg-config --modversion libdpdk
  echo "## gcc"; gcc --version | head -1
} 2>&1 | tee "$OUT"

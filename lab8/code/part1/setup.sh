#!/usr/bin/env bash
# EE542 Lab 8 Part 1 (Step 1.2): install the packages for Parts 1-5 on an
# Ubuntu 22.04 GPU box. Idempotent; run detached:
#   nohup ./setup.sh > setup.log 2>&1 < /dev/null &
# Uses sudo only when not already root (RunPod pods run as root).
set -euo pipefail
SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo"
export DEBIAN_FRONTEND=noninteractive

$SUDO apt-get update
$SUDO apt-get install -y build-essential pkg-config git python3-venv \
  pciutils dpdk dpdk-dev libdpdk-dev libpcap-dev \
  rdma-core libibverbs-dev ibverbs-utils wget curl

# CUDA toolkit 12.6 only (not the `cuda` metapackage, which also pulls a driver).
if [ ! -x /usr/local/cuda-12.6/bin/nvcc ]; then
  . /etc/os-release
  repo="ubuntu${VERSION_ID//./}"
  wget -q "https://developer.download.nvidia.com/compute/cuda/repos/${repo}/x86_64/cuda-keyring_1.1-1_all.deb" -O /tmp/cuda-keyring.deb
  $SUDO dpkg -i /tmp/cuda-keyring.deb
  $SUDO apt-get update
  $SUDO apt-get install -y cuda-toolkit-12-6
fi
grep -q 'cuda-12.6/bin' ~/.bashrc || echo 'export PATH=/usr/local/cuda-12.6/bin:$PATH' >> ~/.bashrc

# Python venv for Parts 2-5.
[ -d ~/venv ] || python3 -m venv ~/venv
. ~/venv/bin/activate
pip install --upgrade pip
pip install torch torchvision onnx onnxscript tensorrt scapy numpy
echo "SETUP DONE"

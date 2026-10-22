#!/usr/bin/env bash
# EE542 Lab 8 Step 6.3 (second half): build the open-source GPUNetIO
# (github.com/NVIDIA-DOCA/gpunetio) and run gpunetio_verbs_write_lat with
# logging on. Expected on a Cloud VM: stops in open_ib_device() with
# "Failed to get RDMA devices list" (no RDMA-capable NIC).
#   CUDA_ARCH=89 ./gpunetio_oss.sh        (89 = L4, 75 = T4, 80 = A30 default)
# Output: data/raw/part6_gpunetio_oss_<host>.log
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
raw="$here/../../data/raw"; mkdir -p "$raw"
log="$raw/part6_gpunetio_oss_$(hostname -s).log"
ARCH="${CUDA_ARCH:-89}"
export PATH=/usr/local/cuda/bin:$PATH
{
  [ -d ~/gpunetio ] || git clone https://github.com/NVIDIA-DOCA/gpunetio ~/gpunetio
  cd ~/gpunetio && echo "commit $(git rev-parse --short HEAD)"
  # Library first, then examples: with -j the examples can link before
  # libdoca_gpunetio_host.so exists ("cannot find -ldoca_gpunetio_host").
  make -j"$(nproc)" install PREFIX="$HOME/gpunetio/install" CUDA_ARCH="$ARCH" 2>&1 | tail -3
  make -j"$(nproc)" install_examples PREFIX="$HOME/gpunetio/install" CUDA_ARCH="$ARCH" 2>&1 | tail -3
  echo "build exit=${PIPESTATUS[0]}"
  ls "$HOME/gpunetio/install/examples"
  export LD_LIBRARY_PATH="$HOME/gpunetio/install/lib:${LD_LIBRARY_PATH:-}"
  # drop the image's forward-compat libcuda (see simple_receive.sh)
  LD_LIBRARY_PATH="$(tr ':' '\n' <<<"$LD_LIBRARY_PATH" | grep -v '/compat' | paste -sd: -)"
  # 00000000:00:04.0 -> 00:04.0 (the short form the examples take)
  gpu="$(nvidia-smi --query-gpu=pci.bus_id --format=csv,noheader | head -1 | awk -F: '{print tolower($(NF-1)":"$NF)}')"
  echo "## GPU short PCI address: $gpu"
  echo "## ibv_devices"; ibv_devices
  echo "## DOCA_GPUNETIO_LOG=6 gpunetio_verbs_write_lat -g $gpu -d mlx5_0"
  DOCA_GPUNETIO_LOG=6 "$HOME/gpunetio/install/examples/gpunetio_verbs_write_lat" -g "$gpu" -d mlx5_0
  echo "exit=$?"
} 2>&1 | tee "$log"

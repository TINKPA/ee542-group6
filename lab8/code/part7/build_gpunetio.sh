#!/usr/bin/env bash
# EE542 Lab 8 Step 7.7: open-source GPUNetIO for the A30 (CUDA_ARCH=80).
# Output: data/raw/part7_build_<host>.log
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
{
  [ -d ~/gpunetio ] || git clone https://github.com/NVIDIA-DOCA/gpunetio ~/gpunetio
  cd ~/gpunetio && echo "commit $(git rev-parse --short HEAD)"
  # library before examples: with -j the examples can link first (Known Issue I-4)
  make -j"$(nproc)" install PREFIX="$HOME/gpunetio/install" CUDA_ARCH=80 2>&1 | tail -3
  make -j"$(nproc)" install_examples PREFIX="$HOME/gpunetio/install" CUDA_ARCH=80 2>&1 | tail -3
  ls "$EX"
  grep -q gpunetio/install ~/.bashrc || cat >> ~/.bashrc <<'RC'
export LD_LIBRARY_PATH=$HOME/gpunetio/install/lib:/opt/mellanox/gdrcopy/src:$LD_LIBRARY_PATH
export EX=$HOME/gpunetio/install/examples
RC
} 2>&1 | tee "$raw/part7_build_$host.log"

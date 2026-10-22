#!/usr/bin/env bash
# EE542 Lab 8 Step 6.1 on a full VM (Ubuntu 22.04 + NVIDIA driver already
# installed): install Docker and the NVIDIA Container Toolkit, then check that a
# container sees the GPU. Output: data/raw/part6_docker_<host>.log
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
raw="$here/../../data/raw"; mkdir -p "$raw"
export DEBIAN_FRONTEND=noninteractive
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
fi
if ! command -v nvidia-ctk >/dev/null; then
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey |
    sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list |
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' |
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
  sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo systemctl restart docker
fi
{
  docker --version; nvidia-ctk --version | head -1
  echo "## docker run --gpus all ubuntu nvidia-smi -L"
  sudo docker run --rm --gpus all ubuntu nvidia-smi -L
} 2>&1 | tee "$raw/part6_docker_$(hostname -s).log"

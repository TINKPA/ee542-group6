#!/usr/bin/env bash
# EE542 Lab 8 Part 6 on a full GPU VM (AWS g6.xlarge, L4, NVIDIA driver AMI),
# exactly as the handout runs it: Docker + Container Toolkit check (6.1), then
# the DOCA container with --gpus all --privileged --net=host (6.2), and inside
# it the simple_receive sample and the open-source GPUNetIO example (6.3).
# Logs land in data/raw/ with the VM's hostname.
#   nohup ./run_part6_vm.sh > ../../data/raw/run6vm.log 2>&1 < /dev/null &
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lab="$(cd "$here/../.." && pwd)"
IMG=nvcr.io/nvidia/doca/doca:devel-cuda13.0.0-3.5.0-devel-host
host="$(hostname -s)"

echo "=== host view"
nvidia-smi --query-gpu=name,driver_version,pci.bus_id --format=csv
lspci | grep -i -E 'ethernet|mellanox|nvidia'
ls /dev/infiniband 2>&1

echo "=== 6.1 docker + nvidia container toolkit"
"$lab/code/part6/docker_gpu_check.sh"

echo "=== 6.2 pull $IMG"
sudo docker pull -q "$IMG"
sudo docker images "$IMG" --format '{{.Repository}}:{{.Tag}} {{.Size}}'

# The container gets the lab tree mounted so its scripts write logs to data/raw.
# hostname is pinned so the logs are named after the VM, not the container id.
run_in() {
  sudo docker run --rm --gpus all --privileged --net=host --hostname "$host" \
    -v "$lab:/root/lab8" "$IMG" bash -c "$1"
}
echo "=== 6.2 doca_caps"
run_in "apt-get install -y -qq pciutils ibverbs-utils >/dev/null 2>&1; /root/lab8/code/part6/doca_explore.sh"
echo "=== 6.3 simple_receive + open-source GPUNetIO"
run_in "SM=89 /root/lab8/code/part6/simple_receive.sh; CUDA_ARCH=89 /root/lab8/code/part6/gpunetio_oss.sh"
sudo chown -R "$(id -u):$(id -g)" "$lab/data/raw"
echo "ALL DONE"

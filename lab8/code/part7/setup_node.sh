#!/usr/bin/env bash
# EE542 Lab 8 Step 7.3 (+ the GRUB half of 7.6): one-time setup of a d7525
# node for GPUNetIO. Run on BOTH nodes right after the experiment is ready:
#   nohup ~/lab8/code/part7/setup_node.sh > ~/lab8/data/raw/part7_setup_$(hostname -s).log 2>&1 &
# Installs the 580-branch open NVIDIA driver + CUDA 13.0 toolkit, apt tools,
# Docker + NVIDIA Container Toolkit with data-root on /mydata, GDRCopy v2.5.2
# in /opt/mellanox/gdrcopy, and turns the IOMMU off in GRUB, then pulls the
# DOCA image. The driver and the IOMMU change share ONE reboot (the handout
# reboots twice; a d7525 reboot takes ~10 min of a 4 h slot). After the
# reboot run after_boot.sh.
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
mountpoint /mydata
df -h / /mydata

sudo apt-get update
sudo apt-get install -y build-essential git "linux-headers-$(uname -r)" pkg-config \
  rdma-core ibverbs-utils libibverbs-dev perftest pciutils ethtool meson ninja-build \
  docker.io curl gnupg

# NVIDIA driver (open kernel module, 580 branch) + CUDA 13.0, from NVIDIA's repo
cd /tmp
wget -q https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt-get update
if apt-cache show nvidia-driver-pinning-580 >/dev/null 2>&1; then
  sudo apt-get install -y nvidia-driver-pinning-580 && sudo apt-get install -y nvidia-open
elif apt-cache show nvidia-open-580 >/dev/null 2>&1; then
  sudo apt-get install -y nvidia-open-580
else
  sudo apt-get install -y nvidia-driver-580-open
fi
sudo apt-get install -y cuda-toolkit-13-0

# Docker data-root on /mydata, then the NVIDIA runtime (nvidia-ctk merges into daemon.json)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo mkdir -p /mydata/docker
echo '{ "data-root": "/mydata/docker" }' | sudo tee /etc/docker/daemon.json
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
sudo docker info --format 'data-root={{.DockerRootDir}}'

# GDRCopy v2.5.2 (library + gdrdrv); gdrdrv is loaded by after_boot.sh
sudo mkdir -p /opt/mellanox
[ -d /opt/mellanox/gdrcopy ] || sudo git clone -b v2.5.2 --depth 1 https://github.com/NVIDIA/gdrcopy /opt/mellanox/gdrcopy
# only libgdrapi + gdrdrv are needed; fall back if the test programs fail to build
cd /opt/mellanox/gdrcopy && { sudo make -j"$(nproc)" CUDA=/usr/local/cuda-13.0 all || \
  sudo make -j"$(nproc)" CUDA=/usr/local/cuda-13.0 config lib driver; }
ls src/libgdrapi.so* src/gdrdrv/gdrdrv.ko

# Step 7.6, GRUB half: IOMMU off from the next boot on
grep -q 'amd_iommu=off' /etc/default/grub || \
  sudo sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT="/&amd_iommu=off iommu=off /' /etc/default/grub
grep GRUB_CMDLINE_LINUX_DEFAULT /etc/default/grub
sudo update-grub

# 22 GB; the pull runs while we wait, before the reboot
sudo docker pull -q nvcr.io/nvidia/doca/doca:devel-cuda13.0.0-3.5.0-devel-host
echo "SETUP DONE $(date) -- now: sudo reboot"

#!/usr/bin/env bash
# EE542 Lab 8 Step 6.2: inside the DOCA container, record the DOCA version,
# the installed libraries, and the devices DOCA finds, plus the PCI/RDMA view
# that explains them. Output: data/raw/part6_doca_caps_<host>.log
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
raw="$here/../../data/raw"; mkdir -p "$raw"
export PATH=/opt/mellanox/doca/tools:/usr/local/cuda/bin:$PATH
log="$raw/part6_doca_caps_$(hostname -s).log"
{
  echo "# $(date -u +%FT%TZ) $(hostname)"; . /etc/os-release; echo "$PRETTY_NAME"; uname -r
  echo "## nvidia-smi"; nvidia-smi --query-gpu=name,driver_version,pci.bus_id --format=csv
  echo "## nvcc"; /usr/local/cuda/bin/nvcc --version | tail -2
  echo "## doca_caps --version"; doca_caps --version
  echo "## doca_caps --list-libs"; doca_caps --list-libs
  echo "## doca_caps --list-devs"; doca_caps --list-devs; echo "exit=$?"
  echo "## lspci (network + 3D/VGA)"; lspci | grep -i -E 'ethernet|network|infiniband|mellanox|nvidia|3d|vga'
  echo "## lspci -nn mellanox (15b3)"; lspci -nn -d 15b3: ; echo "count=$(lspci -d 15b3: | wc -l)"
  echo "## ibv_devices"; ibv_devices
  echo "## /dev/infiniband"; ls -la /dev/infiniband 2>&1
  echo "## ip -br link"; ip -br link 2>&1
  echo "## hugepages"; grep -i huge /proc/meminfo
} 2>&1 | tee "$log"

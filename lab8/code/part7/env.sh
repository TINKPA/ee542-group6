# EE542 Lab 8 Part 7: sourced on a CloudLab node by the other part7 scripts.
# Finds this node's experiment-LAN interface (10.10.1.x), its PCI address and
# RDMA device, and the GPU's PCI address, so no script hardcodes 41:00.0 /
# 25:00.0 / rocep65s0 (the RDMA name changes after the IOMMU reboot, Step 7.6).
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lab="$(cd "$here/../.." && pwd)"
raw="$lab/data/raw"; mkdir -p "$raw"
host="$(hostname -s)"
export PATH=/usr/local/cuda/bin:$PATH
export LD_LIBRARY_PATH=$HOME/gpunetio/install/lib:/opt/mellanox/gdrcopy/src:${LD_LIBRARY_PATH:-}
export EX=$HOME/gpunetio/install/examples
IMG=nvcr.io/nvidia/doca/doca:devel-cuda13.0.0-3.5.0-devel-host

NETDEV="$(ip -br addr | awk '/ 10\.10\.1\./{print $1; exit}')"
NIC="$(ethtool -i "$NETDEV" 2>/dev/null | awk '/bus-info/{sub(/^0000:/,"",$2); print $2}')"
RDEV="$(rdma link 2>/dev/null | awk -v n="$NETDEV" '$0 ~ "netdev "n"( |$)" {split($2,a,"/"); print a[1]; exit}')"
GPU="$(nvidia-smi --query-gpu=pci.bus_id --format=csv,noheader 2>/dev/null | head -1 | sed 's/^0*\([0-9a-fA-F]*:\)//' | tr 'A-F' 'a-f')"
MYIP="$(ip -br addr show "$NETDEV" 2>/dev/null | grep -o '10\.10\.1\.[0-9]*')"

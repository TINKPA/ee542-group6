#!/usr/bin/env bash
# EE542 Lab 8 Step 7.4: check this node against the GPUNetIO install guide.
# Output: data/raw/part7_hw_<host>.log
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
{
  echo "== netdev=$NETDEV nic=$NIC rdma=$RDEV gpu=$GPU ip=$MYIP"
  ip -br addr
  ethtool -i "$NETDEV"
  ibv_devices
  rdma link
  ibv_devinfo -v -d "$RDEV" | grep -E 'hca_id|fw_ver|board_id|GID\['
  lspci | grep -i -E 'mellanox|nvidia'
  lspci -d 15b3: -vv 2>/dev/null | grep -E '^[0-9a-f]|Part number|Product Name' | head -20
  uname -r
  cat /proc/cmdline
  nvidia-smi
  nvidia-smi topo -m
  lspci -tv | head -80
} 2>&1 | tee "$raw/part7_hw_$host.log"

#!/usr/bin/env bash
# EE542 Lab 8 Step 7.3 runtime state, lost on every reboot: 2,048 x 2 MB
# hugepages, gdrdrv, GPU persistence mode, ACS off on every PCIe bridge
# (setpci method from the GPUNetIO installation guide; no BIOS on CloudLab).
#   ~/lab8/code/part7/after_boot.sh 2>&1 | tee ~/lab8/data/raw/part7_afterboot_$(hostname -s).log
set -uo pipefail
cat /proc/cmdline
echo 2048 | sudo tee /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages
grep -i huge /proc/meminfo | head -3
(cd /opt/mellanox/gdrcopy && sudo ./insmod.sh) && lsmod | grep gdrdrv
sudo nvidia-smi -pm 1
for BDF in $(lspci -d "*:*:*" | awk '{print $1}'); do
  sudo setpci -v -s "$BDF" ECAP_ACS+0x6.w > /dev/null 2>&1 || continue
  sudo setpci -v -s "$BDF" ECAP_ACS+0x6.w=0000
done
nvidia-smi --query-gpu=name,driver_version,pci.bus_id,persistence_mode --format=csv
ibv_devices

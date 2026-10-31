#!/usr/bin/env bash
# EE542 Lab 8 Part 7: read-only snapshot of what the nodes know and no other log
# holds (boot state of Step 7.3/7.6, link, ACS, machine, Docker, NIC, dmesg).
# Output: data/raw/part7_state_<tag>_<host>.log   (tag: $1, default "s1")
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
tag="${1:-s1}"
sec() { echo; echo "##### $*"; }
{
  sec date; date -u; uptime -s; cat /proc/cmdline
  sec boot-state
  grep -E 'HugePages_Total|Hugepagesize' /proc/meminfo
  lsmod | grep -E 'gdrdrv|nvidia'
  nvidia-smi --query-gpu=name,driver_version,persistence_mode,pci.bus_id,pcie.link.gen.current,pcie.link.width.current,pcie.link.gen.max,pcie.link.width.max --format=csv
  ls /sys/class/iommu | wc -l
  sudo lspci -vv 2>/dev/null | grep ACSCtl | sort | uniq -c
  sec link
  sudo ethtool "$NETDEV" | grep -E 'Speed|Duplex|Link detected'
  sudo ethtool -a "$NETDEV"
  sudo lspci -s "$NIC" -vv | grep -E 'LnkCap:|LnkSta:'
  sudo lspci -s "$GPU" -vv | grep -E 'LnkCap:|LnkSta:|Region 1'
  sec machine
  cat /etc/os-release | head -4
  lscpu | grep -E 'Model name|Socket|Thread|Core|NUMA'
  free -g | head -2
  numactl -H 2>/dev/null | head -4
  sudo dmidecode -s system-manufacturer; sudo dmidecode -s system-product-name; sudo dmidecode -s bios-version
  ls /sys/devices/system/cpu/cpu0/cpufreq 2>&1 | head -3
  nvidia-smi -q
  sec nic
  sudo devlink dev info "pci/0000:$NIC"
  sudo devlink dev param show "pci/0000:$NIC" name flow_steering_mode
  sudo devlink dev eswitch show "pci/0000:$NIC"
  sudo ethtool -S "$NETDEV" | grep -E 'discard|pause|out_of|retrans|timeout|sequence' | grep -v ': 0$'
  for c in /sys/class/infiniband/$RDEV/ports/1/hw_counters/*; do v=$(cat "$c" 2>/dev/null); [ "${v:-0}" != 0 ] && echo "$(basename "$c") $v"; done
  sec docker
  sudo docker info 2>/dev/null | grep -E 'Server Version|Storage Driver|driver-type|Docker Root Dir|Runtimes'
  sudo docker images --digests
  df -h / /mydata; sudo du -sh /var/lib/containerd /mydata/docker
  nvidia-ctk --version
  sec manifest
  geni-get manifest
  sec dmesg
  sudo dmesg | grep -iE 'nvrm|nvidia|mlx5|iommu|gdrdrv' | tail -120
} 2>&1 | tee "$raw/part7_state_${tag}_$host.log"

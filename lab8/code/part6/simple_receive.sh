#!/usr/bin/env bash
# EE542 Lab 8 Step 6.3: inside the DOCA container, add the GPU's arch to the
# gpunetio_simple_receive meson.build (compile AND link flag lists), build it,
# and run it once per receive mode. Expected on a Cloud VM: stops at
# init_doca_device (no ConnectX/BlueField at the given address).
#   SM=89 ./simple_receive.sh [NIC_PCI]     (89 = L4; 75 T4 and 80 A30 are already listed)
# Output: data/raw/part6_simple_receive_<host>.log
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
raw="$here/../../data/raw"; mkdir -p "$raw"
log="$raw/part6_simple_receive_$(hostname -s).log"
SM="${SM:-89}"
SRC=/opt/mellanox/doca/samples/doca_gpunetio/gpunetio_simple_receive
export PATH=/usr/local/cuda/bin:/opt/mellanox/doca/tools:$PATH
export PKG_CONFIG_PATH="/opt/mellanox/doca/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"
export LD_LIBRARY_PATH="/opt/mellanox/doca/lib/x86_64-linux-gnu:/usr/local/cuda/lib64:${LD_LIBRARY_PATH:-}"
# The image puts /usr/local/cuda-13/compat (a 580 forward-compat libcuda) on
# LD_LIBRARY_PATH. On a host driver NEWER than 580 that stale libcuda wins over
# the host's and CUDA init fails with "unsupported display driver / cuda driver
# combination". Forward compat is only for OLDER host drivers, so drop it.
LD_LIBRARY_PATH="$(tr ':' '\n' <<<"$LD_LIBRARY_PATH" | grep -v '/compat' | paste -sd: -)"; export LD_LIBRARY_PATH
{
  cd "$SRC"
  [ -f meson.build.orig ] || cp meson.build meson.build.orig
  if ! grep -q "sm_$SM" meson.build; then
    # one line after the sm_80 entry in each list
    sed -i "/^nvcc_flags += \['-gencode', 'arch=compute_80,code=sm_80'\]/a nvcc_flags += ['-gencode', 'arch=compute_$SM,code=sm_$SM']" meson.build
    sed -i "/-gencode=arch=compute_80,code=sm_80'\]/a nvcc_flags_link += ['-gencode=arch=compute_$SM,code=sm_$SM']" meson.build
  fi
  echo "## meson.build diff"; diff meson.build.orig meson.build
  rm -rf /tmp/build
  meson setup /tmp/build 2>&1 | tail -15 && ninja -C /tmp/build 2>&1 | tail -5
  ls -la /tmp/build/doca_gpunetio_simple_receive || exit 1
  echo "## cuobjdump archs"; cuobjdump --list-elf /tmp/build/doca_gpunetio_simple_receive 2>/dev/null | grep -o 'sm_[0-9]*' | sort -u | tr '\n' ' '; echo

  gpu="$(nvidia-smi --query-gpu=pci.bus_id --format=csv,noheader | head -1 | awk -F: '{print tolower($(NF-1)":"$NF)}')"
  # NIC: first Mellanox device if any, else the first Ethernet controller, else the arg.
  nic="${1:-$(lspci -d 15b3: | awk 'NR==1{print $1}')}"
  [ -n "$nic" ] || nic="$(lspci | awk '/Ethernet controller/{print $1; exit}')"
  [ -n "$nic" ] || nic="00:00.0"
  echo "## GPU $gpu  NIC $nic"; lspci | grep -i -E 'ethernet|mellanox' || echo "(no Ethernet controller visible in lspci)"
  for e in 0 1 2; do
    echo "## doca_gpunetio_simple_receive -n $nic -g $gpu -e $e"
    /tmp/build/doca_gpunetio_simple_receive -n "$nic" -g "$gpu" -e "$e"
    echo "exit=$?"
  done
} 2>&1 | tee "$log"

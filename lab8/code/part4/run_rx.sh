#!/usr/bin/env bash
# EE542 Lab 8 Parts 3+4: generate the three PCAPs, run the DPDK receiver on
# each, and verify the rebuilt images byte for byte.
#   ./run_rx.sh            (work dir: ../../data/work, logs: ../../data/raw)
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. ~/venv/bin/activate
work="$here/../../data/work"; raw="$here/../../data/raw"; mkdir -p "$work" "$raw"
SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo"
make -s -C "$here" dpdk_rx || exit 1
cd "$work"
log="$raw/part34_$(hostname -s).log"; : > "$log"
python3 "$here/../part3/gen_pcap.py" -o images.pcap | tee -a "$log"
python3 "$here/../part3/gen_pcap.py" -o images_shuf.pcap --shuffle | tee -a "$log"
python3 "$here/../part3/gen_pcap.py" -o images_hard.pcap --shuffle --dup 0.05 --noise 50 | tee -a "$log"
for p in images images_shuf images_hard; do
  echo "=== $p.pcap" | tee -a "$log"
  $SUDO "$here/dpdk_rx" -l 0 --no-huge -m 512 --no-pci --log-level=lib.eal:warning \
    --vdev "net_pcap0,rx_pcap=$p.pcap,tx_pcap=/dev/null" -- "rx_$p.bin" 2>&1 | tee -a "$log"
  python3 "$here/verify.py" frames_orig.bin "rx_$p.bin" 2>&1 | tee -a "$log"
done
echo "log: $log"

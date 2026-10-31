#!/usr/bin/env bash
# EE542 Lab 8 Step 7.8: -p 2 again as root, to see whether the driver's
# "permission denied, allowPeermapping=0" is a privilege gate. rdma_one.sh runs
# as the normal user. Tag in $2 separates runs.
#   gpu_lat_p2_root.sh server|client [tag]
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
role="$1"; tag="${2:-root}"; extra=""
[ "$role" = client ] && extra="-c 10.10.1.1"
log="$raw/part7_gpu_lat_p2_${tag}_${role}_$host.log"
cmd="$EX/gpunetio_verbs_write_lat -g $GPU -d $RDEV -l 3 -p 2 $extra"
echo "\$ sudo DOCA_GPUNETIO_LOG=6 $cmd" > "$log"
sudo env LD_LIBRARY_PATH="$LD_LIBRARY_PATH" DOCA_GPUNETIO_LOG=6 timeout 60 $cmd >> "$log" 2>&1
echo "exit=$?" >> "$log"

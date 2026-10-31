#!/usr/bin/env bash
# EE542 Lab 8 Step 7.5: gpunetio_simple_receive in the DOCA container on node0,
# with the RDMA devices, hugepages and the host's GDRCopy library mounted.
# Expected (handout): stops creating the DOCA Flow port, "Failed to get hws cap".
# Output: data/raw/part7_simple_receive_<host>.log
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# The image's LD_LIBRARY_PATH lists cuda-13/compat (libcuda 580.178.04), which
# shadows the host driver's libcuda (580.196.07) and fails CUDA init with
# "unsupported display driver / cuda driver combination", so the host path goes first.
sudo docker run --rm --privileged --net=host --gpus all --hostname "$host" \
  -v /dev/infiniband:/dev/infiniband -v /dev/hugepages:/dev/hugepages \
  -v /opt/mellanox/gdrcopy/src:/opt/gdrcopy:ro "$IMG" bash -c "
    export LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:/opt/gdrcopy:\$LD_LIBRARY_PATH
    doca_caps --list-devs
    cd /opt/mellanox/doca/samples/doca_gpunetio/gpunetio_simple_receive
    meson setup /tmp/build >/dev/null && ninja -C /tmp/build | tail -2
    for e in 0 1 2; do echo \"=== -e \$e\"; timeout 60 /tmp/build/doca_gpunetio_simple_receive -n $NIC -g $GPU -e \$e; echo \"exit=\$?\"; done
  " 2>&1 | tee "$raw/part7_simple_receive_$host.log"

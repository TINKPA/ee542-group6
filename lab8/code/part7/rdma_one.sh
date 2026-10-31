#!/usr/bin/env bash
# EE542 Lab 8 Steps 7.8-7.10, one side of one test. cl.sh on the Mac starts the
# server on node0, then the client on node1:
#   rdma_one.sh <test> server|client
# Output: data/raw/part7_<test>_<role>_<host>.log
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
test="$1"; role="$2"
case "$test" in
  gpu_lat)     cmd="$EX/gpunetio_verbs_write_lat -g $GPU -d $RDEV -l 3 -p 1" ;;
  gpu_lat_p2)  cmd="$EX/gpunetio_verbs_write_lat -g $GPU -d $RDEV -l 3 -p 2" ;;   # GPU rings the doorbell
  gpu_put_bw)  cmd="$EX/gpunetio_verbs_put_bw -g $GPU -d $RDEV -l 3 -p 1" ;;
  gpu_write_bw) cmd="$EX/gpunetio_verbs_write_bw -g $GPU -d $RDEV -p 1" ;;       # rejects -l: GID 0
  # same tests as root: as a normal user -p 2 stops at "permission denied,
  # allowPeermapping=0" in dmesg; root gets the doorbell mapped into the GPU
  gpu_lat_root)         cmd="$EX/gpunetio_verbs_write_lat -g $GPU -d $RDEV -l 3 -p 1" ;;
  gpu_lat_p2_root)      cmd="$EX/gpunetio_verbs_write_lat -g $GPU -d $RDEV -l 3 -p 2" ;;
  gpu_put_bw_root)      cmd="$EX/gpunetio_verbs_put_bw -g $GPU -d $RDEV -l 3 -p 1" ;;
  gpu_put_bw_p2_root)   cmd="$EX/gpunetio_verbs_put_bw -g $GPU -d $RDEV -l 3 -p 2" ;;
  gpu_write_bw_p2_root) cmd="$EX/gpunetio_verbs_write_bw -g $GPU -d $RDEV -p 2" ;;
  cpu_lat)     cmd="ib_write_lat -d $RDEV -x 3" ;;
  cpu_bw)      cmd="ib_write_bw -d $RDEV -x 3 --report_gbits" ;;
  cpu_lat_all) cmd="ib_write_lat -d $RDEV -x 3 -a" ;;                            # all sizes, for the plot
  cpu_bw_all)  cmd="ib_write_bw -d $RDEV -x 3 --report_gbits -a" ;;
  *) echo "unknown test $test"; exit 1 ;;
esac
if [ "$role" = client ]; then
  case "$test" in gpu_*) cmd="$cmd -c 10.10.1.1" ;; *) cmd="$cmd 10.10.1.1" ;; esac
fi
pre=""; case "$test" in *_root) pre="sudo env LD_LIBRARY_PATH=$LD_LIBRARY_PATH DOCA_GPUNETIO_LOG=6" ;; esac
log="$raw/part7_${test}_${role}_$host.log"
echo "\$ ${pre:-DOCA_GPUNETIO_LOG=6} $cmd" > "$log"
export DOCA_GPUNETIO_LOG=6
if [ "$role" = server ]; then
  nohup $pre $cmd >> "$log" 2>&1 < /dev/null &
  echo $! > "/tmp/part7_$test.pid"
else
  timeout "${TMO:-300}" $pre $cmd >> "$log" 2>&1; echo "exit=$?" >> "$log"
  cat "$log"
fi

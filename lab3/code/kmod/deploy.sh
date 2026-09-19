#!/bin/bash
# EE542 Lab3 Part 3 -- build and load the ee542 congestion-control module on the
# AWS client (the sender; congestion control is a sender-side decision, so an
# scp from client to server only needs it there).
#
# The module registers two algorithms, ee542 (cong_avoid pin) and ee542c
# (cong_control pin), so switching between them is a sysctl write and needs no
# reload.  Reloading is only for a rebuilt .ko, and it is genuinely awkward:
# the per-netns default congestion control holds a module reference, so the
# default must be set back to cubic first, and even then a reference can linger.
# When rmmod fails this script stops instead of silently leaving the old module
# loaded -- otherwise the next measurement reports the previous build's numbers.
# If it does fail, reboot the client; that is faster than hunting the reference.
#
# Usage: deploy.sh [cwnd]        default cwnd=1730 (100 Mbps x 200 ms / 1448 B)
#        deploy.sh unload
# Reads hosts.env written by ../../../lab2/code/aws/aws_lab.sh ips.
set -eu
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/../../../lab2/code/aws/hosts.env"
SSH="ssh -o ServerAliveInterval=15 -o ServerAliveCountMax=4 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"
CWND=${1:-1730}

unload() {
  $SSH ubuntu@$CLIENT_PUB "sudo sysctl -qw net.ipv4.tcp_congestion_control=cubic
    lsmod | grep -q '^ee542_cc' || { echo 'not loaded'; exit 0; }
    for i in \$(seq 1 15); do
      sudo ss -K dst $SERVER_PRIV >/dev/null 2>&1 || true
      sudo rmmod ee542_cc 2>/dev/null && { echo UNLOADED; exit 0; }
      sleep 2
    done
    echo 'RMMOD_FAILED, module still in use:'; lsmod | grep ee542_cc; exit 1"
}

[ "${1:-}" = unload ] && { unload; exit 0; }

echo "== headers + toolchain on client ($CLIENT_PUB) =="
$SSH ubuntu@$CLIENT_PUB 'set -e
  uname -r
  dpkg -s linux-headers-$(uname -r) >/dev/null 2>&1 || {
    sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=180 -qq update
    sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=180 -qq install -y \
      linux-headers-$(uname -r) build-essential >/dev/null; }
  echo HEADERS_OK'

echo "== build =="
$SSH ubuntu@$CLIENT_PUB 'rm -rf ~/kmod && mkdir -p ~/kmod'
scp -q -o StrictHostKeyChecking=accept-new "$DIR/ee542_cc.c" "$DIR/Makefile" ubuntu@$CLIENT_PUB:kmod/
$SSH ubuntu@$CLIENT_PUB 'cd ~/kmod && make 2>&1 | grep -E "CC \[M\]|LD \[M\]|error|warning: .*ee542" ; ls -l ee542_cc.ko'

echo "== load (cwnd=$CWND) =="
unload
$SSH ubuntu@$CLIENT_PUB "sudo insmod ~/kmod/ee542_cc.ko cwnd=$CWND
  GOT=\$(cat /sys/module/ee542_cc/parameters/cwnd)
  [ \"\$GOT\" = '$CWND' ] || { echo \"PARAM_MISMATCH: asked $CWND, loaded \$GOT\"; exit 1; }
  sudo dmesg | grep 'ee542_cc: registered' | tail -1
  echo -n 'available: '; sysctl -n net.ipv4.tcp_available_congestion_control
  echo -n 'current:   '; sysctl -n net.ipv4.tcp_congestion_control"
echo DEPLOY_OK

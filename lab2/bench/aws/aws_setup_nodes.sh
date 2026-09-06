#!/bin/bash
# EE542 Lab2 — bootstrap freshly-launched AWS nodes: tools, lab code, 1 GiB test file.
# client/server: iperf(2)+iperf3+g++, build ftr & ltr, client gets data.bin+data.md5.
# router (when present in hosts.env): ip_forward + second-ENI netplan + iperf.
# Idempotent; usage: aws_setup_nodes.sh   (reads hosts.env written by aws_lab.sh ips)
set -eu
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/hosts.env"
CODE="$DIR/.."
SSHO="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=8"

wait_ssh() { local ip=$1 i; for i in $(seq 1 40); do ssh $SSHO ubuntu@$ip true 2>/dev/null && return 0; sleep 5; done
  echo "ssh timeout $ip"; return 1; }

tools() { ssh $SSHO ubuntu@$1 'cloud-init status --wait >/dev/null 2>&1 || true
  sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=180 -qq update
  sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=180 -qq install -y iperf iperf3 build-essential >/dev/null
  echo TOOLS_OK'; }

endpoint() { # $1 = public ip
  tools $1
  scp $SSHO -q "$CODE/common.hpp" "$CODE/sender.cpp" "$CODE/receiver.cpp" "$CODE/ltr.cpp" "$CODE/Makefile" ubuntu@$1:
  ssh $SSHO ubuntu@$1 'make -s ftr && g++ -O2 -std=c++17 -o ltr ltr.cpp -pthread && echo BUILD_OK'
}

echo "== wait for ssh =="
wait_ssh $CLIENT_PUB; wait_ssh $SERVER_PUB
[ -n "${ROUTER_PUB:-}" ] && wait_ssh $ROUTER_PUB
echo SSH_OK

echo "== client ($CLIENT_PUB) =="; endpoint $CLIENT_PUB
echo "== server ($SERVER_PUB) =="; endpoint $SERVER_PUB

echo "== 1 GiB test file on client =="
ssh $SSHO ubuntu@$CLIENT_PUB '[ -f data.bin ] || dd if=/dev/urandom of=data.bin bs=1M count=1024 status=none
  [ -f data.md5 ] || md5sum data.bin | awk "{print \$1}" > data.md5
  ls -l data.bin; cat data.md5'

if [ -n "${ROUTER_PUB:-}" ]; then
  echo "== router ($ROUTER_PUB) =="
  tools $ROUTER_PUB
  # second ENI (subnet B side) is unconfigured by default: static netplan, no gateway.
  # Interface names are discovered live (nitro: ens5 primary / ens6 secondary).
  ssh $SSHO ubuntu@$ROUTER_PUB '
    PRI=$(ip -o -4 route show default | awk "{print \$5}" | head -1)
    SEC=$(ip -o link | awk -F": " "{print \$2}" | grep -E "^(en|eth)" | grep -v "^$PRI\$" | head -1)
    [ -n "$SEC" ] || { echo "NO_SECONDARY_IFACE"; exit 1; }
    printf "network:\n  version: 2\n  ethernets:\n    %s:\n      addresses: [10.200.2.10/24]\n      mtu: 9001\n" "$SEC" | sudo tee /etc/netplan/60-ethB.yaml >/dev/null
    sudo chmod 600 /etc/netplan/60-ethB.yaml
    sudo netplan apply
    echo "net.ipv4.ip_forward=1" | sudo tee /etc/sysctl.d/99-fwd.conf >/dev/null
    sudo sysctl -qw net.ipv4.ip_forward=1
    echo "ROUTER_NET_OK pri=$PRI sec=$SEC"
    ip -brief addr show | grep -E "^(en|eth)"'
fi
echo "SETUP_OK"

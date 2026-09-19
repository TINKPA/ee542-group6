#!/bin/bash
# EE542 Lab3 Part 3 -- install the patched kernel (built by kbuild.sh) on the
# Lab 2 testbed client and reboot into it.
#
# Congestion control and the retransmission timer are both sender-side, and the
# transfers all run client -> server, so only the client needs the new kernel.
# The server and the router keep the stock one, which is also the honest control:
# any change we measure has to come from the sender.
#
# linux-headers is installed too because ee542_cc.ko must be rebuilt against the
# running kernel after the reboot; deploy.sh does that.
#
# Usage: install_client.sh            # copy debs, dpkg -i, reboot, verify
#        install_client.sh verify     # just print uname -a and the sysctl
set -eu
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/../../../lab2/code/aws/hosts.env"
SSH="ssh -o ServerAliveInterval=15 -o ServerAliveCountMax=4 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"
KVER=7.0.14-ee542

verify() {
  $SSH ubuntu@$CLIENT_PUB 'uname -a
    echo -n "tcp_no_rto_backoff: "; sysctl -n net.ipv4.tcp_no_rto_backoff 2>&1'
}

[ "${1:-}" = verify ] && { verify; exit 0; }

echo "== before =="
$SSH ubuntu@$CLIENT_PUB 'uname -r'

echo "== copy debs =="
scp -q -o StrictHostKeyChecking=accept-new \
  "$DIR/debs/linux-image-${KVER}_"*.deb \
  "$DIR/debs/linux-headers-${KVER}_"*.deb \
  ubuntu@$CLIENT_PUB:/tmp/
$SSH ubuntu@$CLIENT_PUB "ls -l /tmp/linux-*.deb"

echo "== dpkg -i + update-grub =="
$SSH ubuntu@$CLIENT_PUB "set -e
  sudo DEBIAN_FRONTEND=noninteractive dpkg -i /tmp/linux-image-${KVER}_*.deb /tmp/linux-headers-${KVER}_*.deb 2>&1 | grep -Ev '^(Selecting|Preparing|Unpacking)' | tail -5
  sudo update-grub 2>&1 | grep -E 'Found linux image' | head -5
  test -f /boot/vmlinuz-${KVER}"

echo "== reboot =="
$SSH ubuntu@$CLIENT_PUB 'sudo systemctl reboot' 2>/dev/null || true
sleep 40
for i in $(seq 1 30); do
  $SSH -o ConnectTimeout=5 ubuntu@$CLIENT_PUB true 2>/dev/null && break
  sleep 5
done

echo "== after =="
verify
RUNNING=$($SSH ubuntu@$CLIENT_PUB 'uname -r')
[ "$RUNNING" = "$KVER" ] || { echo "WRONG_KERNEL: running $RUNNING, wanted $KVER"; exit 1; }
echo INSTALL_OK

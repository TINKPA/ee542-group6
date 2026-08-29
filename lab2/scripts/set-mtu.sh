#!/usr/bin/env bash
set -euo pipefail

# Run on EVERY node: server, client, and the VyOS router.
# The handout requires the same MTU on all interfaces of all three machines.
# Endpoints carry one interface; the router carries two.
#
#   sudo ./set-mtu.sh 1500
#   sudo ./set-mtu.sh 9001
#
# Note: page 1 of the handout says 9000, pages 5 and 6 say 9001. Using 9001.
# Confirm with the TA and state which you used in the report.

MTU="${1:-}"
case "$MTU" in
  1500|9001|9000) ;;
  *) echo "Usage: sudo ./set-mtu.sh 1500|9001"; exit 2 ;;
esac

# Space separated list of interfaces on THIS machine.
#   endpoints: DEVS="ens33"
#   router:    DEVS="eth1 eth2"
DEVS="${DEVS:-ens33}"

for dev in $DEVS; do
  ip link set dev "$dev" mtu "$MTU"
  echo "$dev -> MTU $(cat /sys/class/net/$dev/mtu)"
done

cat <<NOTE

Verify end to end before trusting this. From an endpoint:
  ping -M do -s $((MTU - 28)) -c 3 <peer_ip>
A payload of $((MTU - 28)) plus 8 ICMP and 20 IP header bytes is exactly $MTU.
If that fails but a smaller size passes, some hop is still at the old MTU.
NOTE

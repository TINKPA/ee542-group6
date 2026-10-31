#!/usr/bin/env bash
# EE542 Lab 8 Part 7: unattended start of the CloudLab slot (10/31 12:00 PT).
# Waits (up to 60 min) until both nodes answer ssh with /mydata mounted, saves
# their hostnames to data/raw/part7_hosts.env, then pushes code/part7 and
# starts setup_node.sh on both (cl.sh push + setup). Stops there: the reboot
# and the measurements are run by hand after checking the setup logs.
#   ./kickoff.sh 2>&1 | tee ../../data/raw/part7_kickoff.log
# Hostnames come from the experiment's List View (cl_hosts.py), with CloudLab's
# canonical names as the fallback when the saved web login has expired.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lab="$(cd "$here/../.." && pwd)"
hosts="$lab/data/raw/part7_hosts.env"
D0=node0.g6lab8.doca-gpu-pg0.wisc.cloudlab.us
D1=node1.g6lab8.doca-gpu-pg0.wisc.cloudlab.us
up() { ssh -i ~/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=10 \
         -o StrictHostKeyChecking=accept-new "huacongt@$1" 'mountpoint -q /mydata' 2>/dev/null; }

deadline=$((SECONDS + 3600))
while :; do
  N0= N1=
  eval "$(cd "$here" && uv run -q --with playwright python cl_hosts.py 2>&1 | grep -E '^N[01]=[A-Za-z0-9.-]+$')"
  for pair in "${N0:-$D0} ${N1:-$D1}" "$D0 $D1"; do
    set -- $pair
    if up "$1" && up "$2"; then N0=$1 N1=$2; break 2; fi
  done
  echo "$(date +%H:%M:%S) nodes not ready yet (list view: ${N0:-none} ${N1:-none})"
  [ "$SECONDS" -gt "$deadline" ] && { echo "TIMEOUT: nodes never became reachable"; exit 1; }
  sleep 60
done

echo "$(date +%H:%M:%S) nodes up: N0=$N0 N1=$N1"
printf 'export N0=%s N1=%s\n' "$N0" "$N1" > "$hosts"
export N0 N1
"$here/cl.sh" push || { echo "PUSH FAILED"; exit 1; }
"$here/cl.sh" setup
sleep 180
"$here/cl.sh" status
echo "KICKOFF DONE $(date +%H:%M:%S) -- setup running; next: ./cl.sh status until SETUP DONE, then reboot"

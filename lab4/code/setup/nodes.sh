#!/bin/bash
# Switch the cluster between one and two nodes, from the Mac.
#
# This is all Section 3 is: the master's `workers` file lists who runs a
# DataNode and a NodeManager, so the single/two-node comparison is a swap of
# that file plus a restart.  Stopping first matters -- leaving the old daemons
# up gives a two-node cluster that still schedules everything on the master.
#
# Usage: nodes.sh one|two [--format]
set -eu
DIR="$(cd "$(dirname "$0")" && pwd)"
CODE="$(dirname "$DIR")"
WHICH=${1:?usage: nodes.sh one|two [--format]}
. "$CODE/aws/l4_hosts.env"
SSH="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null ubuntu@$L4_MASTER_PUB"

$SSH '. /opt/lab4/env.sh; stop-yarn.sh; stop-dfs.sh' >/dev/null 2>&1 || true
for H in "$L4_MASTER_PUB" "$L4_WORKER_PUB"; do
  scp -q -o StrictHostKeyChecking=no "$CODE"/setup/conf/*.xml ubuntu@"$H":/usr/local/hadoop/etc/hadoop/
done
scp -q -o StrictHostKeyChecking=no "$CODE/setup/conf/workers.$WHICH" \
  ubuntu@"$L4_MASTER_PUB":/usr/local/hadoop/etc/hadoop/workers

if [ "${2:-}" = --format ]; then
  $SSH '. /opt/lab4/env.sh; hdfs namenode -format -force -nonInteractive' >/dev/null
fi
$SSH '. /opt/lab4/env.sh; start-dfs.sh && start-yarn.sh && hdfs dfsadmin -safemode wait && hdfs dfsadmin -report | grep -E "^(Live datanodes|Name:)"'

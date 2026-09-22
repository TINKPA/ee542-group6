#!/bin/bash
# Runs on the Mac.  Brings two fresh EC2 instances to a started cluster.
#
# Reads aws/l4_hosts.env (written by aws/lab4_cluster.sh ips).  Nothing is
# copied by hand and no step is done in an interactive ssh session, so the whole
# build is re-runnable after a teardown.
#
# Usage: deploy.sh [one|two]     (how many nodes the cluster starts with)
set -eu
DIR="$(cd "$(dirname "$0")" && pwd)"
CODE="$(dirname "$DIR")"
NODES=${1:-one}
. "$CODE/aws/l4_hosts.env"
SSH="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

for H in "$L4_MASTER_PUB" "$L4_WORKER_PUB"; do
  # /opt is root-owned on a stock Ubuntu AMI, so rsync cannot create the
  # target directory itself.
  $SSH ubuntu@"$H" 'sudo mkdir -p /opt/lab4 && sudo chown -R ubuntu /opt/lab4'
  rsync -az -e "$SSH" --exclude local/ --exclude __pycache__ "$CODE/" ubuntu@"$H":/opt/lab4/
  $SSH ubuntu@"$H" 'bash /opt/lab4/setup/install_node.sh'
  # Both nodes must resolve master and worker1; the conf files use those names.
  $SSH ubuntu@"$H" "sudo sed -i '/ master\$/d;/ worker1\$/d' /etc/hosts && \
    echo '$L4_MASTER_PRIV master' | sudo tee -a /etc/hosts >/dev/null && \
    echo '$L4_WORKER_PRIV worker1' | sudo tee -a /etc/hosts >/dev/null"
done

# start-dfs.sh starts the remote DataNode over ssh from the master, so the
# master needs a key the worker trusts.  The handout never mentions this and
# the cluster simply will not start without it.
$SSH ubuntu@"$L4_MASTER_PUB" '[ -f ~/.ssh/id_ed25519 ] || ssh-keygen -q -t ed25519 -N "" -f ~/.ssh/id_ed25519'
KEY=$($SSH ubuntu@"$L4_MASTER_PUB" 'cat ~/.ssh/id_ed25519.pub')
for H in "$L4_MASTER_PUB" "$L4_WORKER_PUB"; do
  $SSH ubuntu@"$H" "grep -qF '$KEY' ~/.ssh/authorized_keys || echo '$KEY' >> ~/.ssh/authorized_keys"
done
$SSH ubuntu@"$L4_MASTER_PUB" "printf 'Host *\n  StrictHostKeyChecking no\n  UserKnownHostsFile /dev/null\n' > ~/.ssh/config && chmod 600 ~/.ssh/config"

"$DIR/nodes.sh" "$NODES" --format
echo "cluster up.  NameNode UI: http://$L4_MASTER_PUB:9870   YARN: http://$L4_MASTER_PUB:8088"

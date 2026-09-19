#!/bin/bash
# EE542 Lab3 Part 3, modification (1): build a linux-aws kernel with the TCP
# exponential RTO backoff removed.
#
# The backoff lives in tcp_retransmit_timer() in net/ipv4/tcp_timer.c, which is
# compiled into vmlinux (TCP core is obj-y), so unlike the congestion-control
# module this genuinely needs a kernel build.
#
# The handout budgets ~10 hours for its method 1 on a micro instance and tells you
# to use method 2 (incremental, "make oldconfig; make -jN bindeb-pkg") instead.
# We use method 2 with two adjustments:
#   - A disposable build host, terminated afterwards, so the testbed nodes keep
#     their state.  It is only 2 vCPU: this account's plan launches free-tier
#     eligible types only, and every one of those has 2 vCPU (m7i-flex.large is
#     the largest, 2 vCPU / 8 GiB).  NOTE: run-instances --dry-run does NOT catch
#     this -- it returned DryRunOperation for c7i-flex.8xlarge and the real launch
#     then failed with InvalidParameterCombination "not eligible for Free Tier".
#   - make localmodconfig against the TARGET node's lsmod instead of the stock
#     Ubuntu config.  The generic config builds thousands of modules that an EC2
#     guest never loads; trimming to what the client actually has loaded is what
#     makes a 2-core build finish in well under an hour.  Built-in options are
#     untouched, so the ENA and NVMe drivers survive, and we verify by booting
#     the disposable host before touching the client.
#
# Usage: kbuild.sh up | lsmod | src | build | fetch | testboot | start | stop | down | ssh
# Reuses the Lab 2 VPC/subnet/SG/key from ../../../lab2/code/aws/aws_state.env.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
AWSDIR="$DIR/../../../lab2/code/aws"
STATE="$DIR/kbuild_state.env"
export AWS_PAGER=""
REGION=${REGION:-us-west-2}
TYPE=${TYPE:-m7i-flex.large}   # largest free-tier-eligible type: 2 vCPU / 8 GiB
DISK=${DISK:-60}
A() { aws --region "$REGION" --output text "$@"; }
. "$AWSDIR/aws_state.env"
[ -f "$STATE" ] && . "$STATE"
SSHO="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"
B() { ssh $SSHO ubuntu@$BPUB "$@"; }

case "${1:?up|lsmod|src|build|fetch|testboot|start|stop|down|ssh}" in
lsmod)
  # capture the target node's loaded modules; localmodconfig is driven by this
  . "$AWSDIR/hosts.env"
  ssh $SSHO ubuntu@$CLIENT_PUB 'lsmod' > "$DIR/target_lsmod.txt"
  echo "$(( $(wc -l < "$DIR/target_lsmod.txt") - 1 )) modules loaded on the client -> $DIR/target_lsmod.txt"
  ;;
up)
  [ -n "${IBLD:-}" ] && { echo "build host already exists: $IBLD"; exit 0; }
  set -e
  AMI=$(A ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id --query Parameter.Value)
  IBLD=$(A ec2 run-instances --image-id $AMI --instance-type $TYPE --key-name ee542-lab2 \
    --subnet-id $SUBA --associate-public-ip-address --security-group-ids $SG \
    --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=$DISK,VolumeType=gp3,DeleteOnTermination=true}" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=ee542-kbuild},{Key=project,Value=ee542-lab3-kbuild}]" \
    --query 'Instances[0].InstanceId')
  echo "IBLD=$IBLD" >> "$STATE"; echo "build host=$IBLD ($TYPE, ${DISK}GB)"
  A ec2 wait instance-running --instance-ids $IBLD
  BPUB=$(A ec2 describe-instances --instance-ids $IBLD --query 'Reservations[0].Instances[0].PublicIpAddress')
  echo "BPUB=$BPUB" >> "$STATE"; echo "BPUB=$BPUB"
  for i in $(seq 1 40); do ssh $SSHO -o BatchMode=yes ubuntu@$BPUB true 2>/dev/null && break; sleep 5; done
  ssh $SSHO ubuntu@$BPUB 'nproc; free -g | head -2; df -h / | tail -1'
  ;;
src)
  : ${BPUB:?run up first}
  set -e
  # Ubuntu 24.04 uses the deb822 sources file; the handout's "uncomment deb-src
  # in /etc/apt/sources.list" has to be done there instead.
  B 'set -e
    sudo sed -i "s/^Types: deb$/Types: deb deb-src/" /etc/apt/sources.list.d/ubuntu.sources
    grep -m1 "^Types:" /etc/apt/sources.list.d/ubuntu.sources
    sudo DEBIAN_FRONTEND=noninteractive apt-get -qq update
    sudo DEBIAN_FRONTEND=noninteractive apt-get -qq install -y build-essential fakeroot libncurses-dev \
      bison flex libssl-dev libelf-dev libdw-dev dwarves bc rsync kmod cpio zstd debhelper >/dev/null
    echo TOOLCHAIN_OK'
  B 'set -e
    mkdir -p ~/k && cd ~/k
    PKG=$(dpkg -S /boot/vmlinuz-$(uname -r) 2>/dev/null | cut -d: -f1 | head -1)
    echo "running kernel package: ${PKG:-<none>}  release: $(uname -r)"
    apt-get source linux-image-unsigned-$(uname -r) 2>&1 | tail -5 || \
    apt-get source ${PKG:-linux-aws} 2>&1 | tail -5
    ls -d ~/k/*/ 2>/dev/null; ls ~/k | head'
  ;;
build)
  : ${BPUB:?run up first}
  [ -f "$DIR/target_lsmod.txt" ] || { echo "run ./kbuild.sh lsmod first"; exit 1; }
  scp $SSHO "$DIR/target_lsmod.txt" ubuntu@$BPUB:~/target_lsmod.txt
  B 'set -e
    cd $(ls -d ~/k/*/ | head -1)
    cp /boot/config-$(uname -r) .config
    # Ubuntu configs are signed-module configs; without the vendor keys the build
    # stops looking for debian/canonical-certs.pem.
    scripts/config --disable MODULE_SIG_ALL --disable MODULE_SIG --disable SYSTEM_TRUSTED_KEYS --disable SYSTEM_REVOCATION_KEYS
    scripts/config --disable DEBUG_INFO_BTF --disable DEBUG_INFO_DWARF5 --enable DEBUG_INFO_NONE
    yes "" | make LSMOD=$HOME/target_lsmod.txt localmodconfig >/dev/null 2>&1 || true
    # localmodconfig keeps only what the target had loaded, and inet_diag is
    # built-in on stock Ubuntu so it never appears in lsmod -- it gets dropped.
    # Without it `ss -ti` silently falls back to parsing /proc/net/tcp, which has
    # no bytes_sent/bytes_retrans/rtt and reports rto in USER_HZ seconds, and
    # every sender-side measurement in this lab reads ss, so put it back.
    scripts/config --enable INET_DIAG --enable INET_TCP_DIAG --enable INET_DIAG_DESTROY
    make olddefconfig >/dev/null
    grep -E "^CONFIG_INET_(TCP_)?DIAG" .config
    echo "modules to build: $(grep -c "=m$" .config)   (stock config has thousands)"
    echo "building on $(nproc) cores, $(date -u +%H:%M:%SZ)"
    time make -j4 bindeb-pkg LOCALVERSION=-ee542 2>&1 | tail -25
    ls -l ~/k/*.deb'
  ;;
fetch)
  : ${BPUB:?run up first}
  mkdir -p "$DIR/debs"
  scp $SSHO "ubuntu@$BPUB:~/k/*.deb" "$DIR/debs/" && ls -l "$DIR/debs/"
  ;;
testboot)
  : ${BPUB:?run up first}
  B 'set -e
    cd ~/k && sudo dpkg -i linux-image-*ee542*.deb linux-headers-*ee542*.deb 2>&1 | tail -5
    sudo update-grub 2>&1 | tail -3
    echo "rebooting into the new kernel"'
  B 'sudo systemctl reboot' || true
  for i in $(seq 1 40); do sleep 5; ssh $SSHO -o BatchMode=yes ubuntu@$BPUB 'uname -a' 2>/dev/null && break; done
  ;;
start)
  : ${IBLD:?no build host in state}
  A ec2 start-instances --instance-ids $IBLD --query 'StartingInstances[].CurrentState.Name'
  A ec2 wait instance-running --instance-ids $IBLD
  BPUB=$(A ec2 describe-instances --instance-ids $IBLD --query 'Reservations[0].Instances[0].PublicIpAddress')
  sed -i.bak "/^BPUB=/d" "$STATE"; echo "BPUB=$BPUB" >> "$STATE"; echo "BPUB=$BPUB"
  for i in $(seq 1 40); do ssh $SSHO -o BatchMode=yes ubuntu@$BPUB 'uname -r' 2>/dev/null && break; sleep 5; done
  ;;
stop) : ${IBLD:?no build host in state}; A ec2 stop-instances --instance-ids $IBLD --query 'StoppingInstances[].CurrentState.Name';;
ssh) ssh $SSHO ubuntu@$BPUB;;
down)
  [ -z "${IBLD:-}" ] && { echo "nothing to terminate"; exit 0; }
  A ec2 terminate-instances --instance-ids $IBLD --query 'TerminatingInstances[].CurrentState.Name'
  mv "$STATE" "$STATE.$(date +%s).bak"
  echo DOWN_OK
  ;;
esac

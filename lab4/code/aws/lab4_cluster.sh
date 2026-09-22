#!/bin/bash
# EE542 Lab4 -- provision the two-node Hadoop/Spark cluster on EC2.
#
# Default VPC and one security group, like Lab 5: there is no topology to build
# here, both nodes just need to reach each other and us.  (Lab 3's four-subnet
# script exists because that lab shaped traffic on the experiment interface;
# nothing in Lab 4 does.)
#
# Instance type is c7i-flex.large, not the handout's t2.medium.  t2 is a
# burstable type: once CPU credits run out the instance is throttled, and
# Sections 3 and 6 are entirely about execution time, so a throttled run would
# silently corrupt the only numbers the lab produces (errata E-15).  Same
# reasoning and same type as Lab 2/3/5.  STOP THE INSTANCES WHEN DONE.
#
# Usage: lab4_cluster.sh up | ips | status | stop | start | down
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
STATE="$DIR/lab4_state.env"
HOSTS="$DIR/l4_hosts.env"
export AWS_PAGER=""
REGION=${REGION:-us-west-2}
TYPE=${TYPE:-c7i-flex.large}
KEYNAME=${KEYNAME:-ee542-lab4}
DISK=${DISK:-40}          # the large corpus is ~1 GB, x2 replicas, plus job output

A() { aws --region "$REGION" --output text "$@"; }
sv() { echo "$1=$2" >> "$STATE"; }
[ -f "$STATE" ] && . "$STATE"

case "${1:?usage: lab4_cluster.sh up|ips|status|stop|start|down}" in
up)
  [ -n "${IMASTER:-}" ] && { echo "already provisioned: $IMASTER $IWORKER"; exit 0; }
  set -e
  VPC=$(A ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId')
  SUB=$(A ec2 describe-subnets --filters Name=vpc-id,Values=$VPC --query 'Subnets[0].SubnetId')
  sv VPC $VPC; sv SUB $SUB
  SG=$(A ec2 create-security-group --group-name ee542-lab4 --description "ee542 lab4" --vpc-id $VPC --query GroupId); sv SG $SG
  # Everything inside the VPC (the cluster's own RPC ports are many and the
  # handout's "50070, 8088, etc." does not enumerate them), plus ssh and the two
  # web UIs from outside.  9870 not 50070: the handout names the Hadoop 2.x
  # NameNode port (errata E-1).
  A ec2 authorize-security-group-ingress --group-id $SG --protocol all --source-group $SG >/dev/null
  for P in 22 9870 8088 18080; do
    A ec2 authorize-security-group-ingress --group-id $SG --protocol tcp --port $P --cidr 0.0.0.0/0 >/dev/null
  done
  # Import this machine's public key rather than assuming an earlier lab's key
  # pair: ee542-lab2/lab3 were imported from the MacBook Pro, and whichever
  # machine drives the cluster has to be the one that can ssh into it.
  A ec2 import-key-pair --key-name $KEYNAME --public-key-material fileb://$HOME/.ssh/id_ed25519.pub >/dev/null 2>&1 || true
  AMI=$(A ssm get-parameter --name /aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp2/ami-id --query Parameter.Value)
  echo "AMI=$AMI"
  for ROLE in master worker; do
    I=$(A ec2 run-instances --image-id $AMI --instance-type $TYPE --key-name $KEYNAME \
        --security-group-ids $SG --subnet-id $SUB --associate-public-ip-address \
        --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=$DISK,VolumeType=gp3}" \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=ee542l4-$ROLE},{Key=project,Value=ee542-lab4}]" \
        --query 'Instances[0].InstanceId')
    [ "$ROLE" = master ] && sv IMASTER $I || sv IWORKER $I
    echo "$ROLE=$I"
  done
  . "$STATE"
  A ec2 wait instance-running --instance-ids $IMASTER $IWORKER
  "$0" ips
  ;;

ips)
  q() { A ec2 describe-instances --instance-ids "$1" --query "Reservations[0].Instances[0].$2"; }
  {
    echo "L4_MASTER_PUB=$(q $IMASTER PublicIpAddress)"
    echo "L4_MASTER_PRIV=$(q $IMASTER PrivateIpAddress)"
    echo "L4_WORKER_PUB=$(q $IWORKER PublicIpAddress)"
    echo "L4_WORKER_PRIV=$(q $IWORKER PrivateIpAddress)"
  } > "$HOSTS"
  cat "$HOSTS"
  ;;

status) A ec2 describe-instances --instance-ids $IMASTER $IWORKER \
          --query 'Reservations[].Instances[].[Tags[?Key==`Name`]|[0].Value,InstanceId,State.Name,PublicIpAddress]' ;;
stop)   A ec2 stop-instances  --instance-ids $IMASTER $IWORKER ;;
start)  A ec2 start-instances --instance-ids $IMASTER $IWORKER
        A ec2 wait instance-running --instance-ids $IMASTER $IWORKER
        "$0" ips ;;  # public IPs change across a stop/start
down)
  A ec2 terminate-instances --instance-ids $IMASTER $IWORKER
  A ec2 wait instance-terminated --instance-ids $IMASTER $IWORKER
  A ec2 delete-security-group --group-id $SG || true
  mv "$STATE" "$STATE.$(date +%s).bak"; rm -f "$HOSTS"
  ;;
*) echo "usage: lab4_cluster.sh up|ips|status|stop|start|down" >&2; exit 2 ;;
esac

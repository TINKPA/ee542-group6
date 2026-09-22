#!/bin/bash
# EE542 Lab5 — provision one Ubuntu EC2 node to host ThingsBoard CE.
#
# Unlike Lab 2/3 there is no topology to build: the phone talks to one public
# endpoint, so we sit in the account's DEFAULT VPC and only add a security
# group.  The handout suggests opening all traffic to 0.0.0.0/0; we instead
# open exactly the four ports the lab uses, which is defensible in the report
# and costs nothing in functionality:
#   22   ssh          8080  ThingsBoard UI + HTTP device API (plaintext)
#   1883 MQTT         5683/udp CoAP
#   80   ACME HTTP-01 challenge   443  the https endpoint the phones actually use
# 80/443 are for tb_tls.sh: OwnTracks on iOS refuses plaintext http entirely
# (errata E-6), so the phone leg needs TLS and TLS needs these two open.
#
# ThingsBoard CE + PostgreSQL needs ~4 GiB; t2.micro thrashes (the handout says
# free tier is "awfully slow").  c7i-flex.large = 2 vCPU / 4 GiB, free-tier
# eligible on this account, ~$0.085/h.  STOP IT WHEN DONE.
#
# Usage: aws_tb.sh up | ip | status | stop | start | down
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
STATE="$DIR/tb_state.env"
export AWS_PAGER=""
REGION=${REGION:-us-west-2}
TYPE=${TYPE:-c7i-flex.large}
KEYNAME=${KEYNAME:-ee542-lab2}
DISK=${DISK:-30}

A() { aws --region "$REGION" --output text "$@"; }
sv() { echo "$1=$2" >> "$STATE"; }
[ -f "$STATE" ] && . "$STATE"

case "${1:?usage: aws_tb.sh up|ip|status|stop|start|down}" in
up)
  [ -n "${ITB:-}" ] && { echo "already provisioned: $ITB"; exit 0; }
  set -e
  # The 2026-09-21 teardown deleted every key pair, so import ours if absent
  # (idempotent: `|| true` swallows the InvalidKeyPair.Duplicate when it exists).
  A ec2 import-key-pair --key-name "$KEYNAME" \
     --public-key-material "fileb://$HOME/.ssh/id_ed25519.pub" >/dev/null 2>&1 || true

  VPC=$(A ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId')
  SUB=$(A ec2 describe-subnets --filters Name=vpc-id,Values=$VPC --query 'Subnets[0].SubnetId')
  echo "VPC=$VPC SUB=$SUB"

  SG=$(A ec2 create-security-group --group-name ee542-lab5-tb \
        --description "ee542 lab5 thingsboard" --vpc-id "$VPC" \
        --tag-specifications 'ResourceType=security-group,Tags=[{Key=Name,Value=ee542-lab5-sg},{Key=project,Value=ee542-lab5}]' \
        --query GroupId)
  for p in 22 80 443 8080 1883; do
    A ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port $p --cidr 0.0.0.0/0 >/dev/null
  done
  A ec2 authorize-security-group-ingress --group-id "$SG" --protocol udp --port 5683 --cidr 0.0.0.0/0 >/dev/null
  sv SG "$SG"; echo "SG=$SG"

  AMI=$(A ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id --query Parameter.Value)
  echo "AMI=$AMI type=$TYPE"
  ITB=$(A ec2 run-instances --image-id "$AMI" --instance-type "$TYPE" \
        --key-name "$KEYNAME" --security-group-ids "$SG" --subnet-id "$SUB" \
        --associate-public-ip-address \
        --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=$DISK,VolumeType=gp3}" \
        --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=ee542-lab5-tb},{Key=project,Value=ee542-lab5}]' \
        --query 'Instances[0].InstanceId')
  sv ITB "$ITB"; echo "ITB=$ITB"
  A ec2 wait instance-running --instance-ids "$ITB"
  "$0" ip
  ;;
ip)
  [ -z "${ITB:-}" ] && { echo "run up first"; exit 1; }
  A ec2 describe-instances --instance-ids "$ITB" \
    --query 'Reservations[0].Instances[0].PublicIpAddress'
  ;;
status)
  [ -z "${ITB:-}" ] && { echo "run up first"; exit 1; }
  A ec2 describe-instances --instance-ids "$ITB" \
    --query 'Reservations[0].Instances[0].[InstanceId,State.Name,InstanceType,PublicIpAddress]' \
    --output table
  ;;
stop)  A ec2 stop-instances  --instance-ids "${ITB}" --query 'StoppingInstances[0].CurrentState.Name' ;;
start) A ec2 start-instances --instance-ids "${ITB}" --query 'StartingInstances[0].CurrentState.Name'
       A ec2 wait instance-running --instance-ids "${ITB}"; "$0" ip ;;
down)
  set -e
  A ec2 terminate-instances --instance-ids "${ITB}" --query 'TerminatingInstances[0].CurrentState.Name'
  A ec2 wait instance-terminated --instance-ids "${ITB}"
  A ec2 delete-security-group --group-id "${SG}" || true
  rm -f "$STATE"; echo "DOWN_OK"
  ;;
*) echo "unknown: $1"; exit 1 ;;
esac

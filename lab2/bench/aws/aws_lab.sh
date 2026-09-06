#!/bin/bash
# EE542 Lab2 — provision the handout's 3-node AWS topology from the Mac.
#   client(10.200.1.83, subnet A) ── router(10.200.1.10 | 10.200.2.10) ── server(10.200.2.48, subnet B)
# VPC 10.200.0.0/16, both subnets in one AZ. Traffic between the two subnets is
# forced through the router instance via subnet route tables pointing at its two
# ENIs (AWS "more specific routing"); src/dst check disabled on both router ENIs.
# Router gets an Elastic IP (auto public IPs are NOT re-assigned after stop/start
# on multi-ENI instances); client/server use auto public IPs (`ips` re-queries).
#
# Staged bring-up (new accounts start with a 5-vCPU quota, so the router may
# have to wait for a quota increase): netup -> endpoints -> router.
# `up` runs all three. Until `router` runs, client<->server traffic goes direct
# over the VPC local route; `router` inserts the middlebox routes.
# Free-plan accounts only launch free-tier-eligible types; c7i-flex.large is
# eligible, 2 vCPU / 4 GiB / 12.5 Gbit burst. Cost ≈ $0.26/h for 3 nodes.
# Usage: aws_lab.sh up | netup | endpoints | router | ips | status | stop | start | down
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
STATE="$DIR/aws_state.env"
export AWS_PAGER=""
REGION=${REGION:-us-west-2}
AZ=${AZ:-us-west-2a}
TYPE=${TYPE:-c7i-flex.large}
RTYPE=${RTYPE:-$TYPE}
KEYNAME=ee542-lab2
CLI_IP=10.200.1.83; SRV_IP=10.200.2.48; RT_A_IP=10.200.1.10; RT_B_IP=10.200.2.10

A() { aws --region "$REGION" --output text "$@"; }
sv() { echo "$1=$2" >> "$STATE"; }
tg() { echo "ResourceType=$1,Tags=[{Key=Name,Value=ee542-$2},{Key=project,Value=ee542-lab2}]"; }
[ -f "$STATE" ] && . "$STATE"

case "${1:?usage: aws_lab.sh up|netup|endpoints|router|ips|status|stop|start|down}" in
netup)
  [ -n "${VPC:-}" ] && { echo "netup already done ($STATE)"; exit 0; }
  set -e
  VPC=$(A ec2 create-vpc --cidr-block 10.200.0.0/16 --tag-specifications "$(tg vpc vpc)" --query Vpc.VpcId); sv VPC $VPC; echo "VPC=$VPC"
  A ec2 modify-vpc-attribute --vpc-id $VPC --enable-dns-hostnames
  SUBA=$(A ec2 create-subnet --vpc-id $VPC --cidr-block 10.200.1.0/24 --availability-zone $AZ --tag-specifications "$(tg subnet subA)" --query Subnet.SubnetId); sv SUBA $SUBA
  SUBB=$(A ec2 create-subnet --vpc-id $VPC --cidr-block 10.200.2.0/24 --availability-zone $AZ --tag-specifications "$(tg subnet subB)" --query Subnet.SubnetId); sv SUBB $SUBB
  IGW=$(A ec2 create-internet-gateway --tag-specifications "$(tg internet-gateway igw)" --query InternetGateway.InternetGatewayId); sv IGW $IGW
  A ec2 attach-internet-gateway --internet-gateway-id $IGW --vpc-id $VPC
  RTA=$(A ec2 create-route-table --vpc-id $VPC --tag-specifications "$(tg route-table rtA)" --query RouteTable.RouteTableId); sv RTA $RTA
  RTB=$(A ec2 create-route-table --vpc-id $VPC --tag-specifications "$(tg route-table rtB)" --query RouteTable.RouteTableId); sv RTB $RTB
  A ec2 associate-route-table --route-table-id $RTA --subnet-id $SUBA >/dev/null
  A ec2 associate-route-table --route-table-id $RTB --subnet-id $SUBB >/dev/null
  A ec2 create-route --route-table-id $RTA --destination-cidr-block 0.0.0.0/0 --gateway-id $IGW >/dev/null
  A ec2 create-route --route-table-id $RTB --destination-cidr-block 0.0.0.0/0 --gateway-id $IGW >/dev/null
  SG=$(A ec2 create-security-group --group-name ee542-lab2 --description "ee542 lab2" --vpc-id $VPC --tag-specifications "$(tg security-group sg)" --query GroupId); sv SG $SG
  A ec2 authorize-security-group-ingress --group-id $SG --protocol all --cidr 10.200.0.0/16 >/dev/null
  A ec2 authorize-security-group-ingress --group-id $SG --protocol tcp --port 22 --cidr 0.0.0.0/0 >/dev/null
  A ec2 import-key-pair --key-name $KEYNAME --public-key-material fileb://$HOME/.ssh/id_ed25519.pub >/dev/null 2>&1 || true
  echo "NETUP_OK"
  ;;
endpoints)
  [ -z "${VPC:-}" ] && { echo "run netup first"; exit 1; }
  [ -n "${ICLI:-}" ] && { echo "endpoints already launched"; exit 0; }
  set -e
  AMI=$(A ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id --query Parameter.Value)
  echo "AMI=$AMI type=$TYPE az=$AZ"
  ICLI=$(A ec2 run-instances --image-id $AMI --instance-type $TYPE --key-name $KEYNAME \
    --subnet-id $SUBA --private-ip-address $CLI_IP --associate-public-ip-address \
    --security-group-ids $SG --tag-specifications "$(tg instance client)" \
    --query 'Instances[0].InstanceId'); sv ICLI $ICLI; echo "client=$ICLI"
  ISRV=$(A ec2 run-instances --image-id $AMI --instance-type $TYPE --key-name $KEYNAME \
    --subnet-id $SUBB --private-ip-address $SRV_IP --associate-public-ip-address \
    --security-group-ids $SG --tag-specifications "$(tg instance server)" \
    --query 'Instances[0].InstanceId'); sv ISRV $ISRV; echo "server=$ISRV"
  echo "waiting for running..."
  A ec2 wait instance-running --instance-ids $ICLI $ISRV
  echo "ENDPOINTS_OK"
  "$0" ips
  ;;
router)
  [ -z "${VPC:-}" ] && { echo "run netup first"; exit 1; }
  [ -n "${IRTR:-}" ] && { echo "router already launched"; exit 0; }
  set -e
  AMI=$(A ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id --query Parameter.Value)
  IRTR=$(A ec2 run-instances --image-id $AMI --instance-type $RTYPE --key-name $KEYNAME \
    --subnet-id $SUBA --private-ip-address $RT_A_IP --associate-public-ip-address \
    --security-group-ids $SG --tag-specifications "$(tg instance router)" \
    --query 'Instances[0].InstanceId'); sv IRTR $IRTR; echo "router=$IRTR"
  A ec2 wait instance-running --instance-ids $IRTR
  ENIA=$(A ec2 describe-instances --instance-ids $IRTR \
    --query 'Reservations[0].Instances[0].NetworkInterfaces[?Attachment.DeviceIndex==`0`].NetworkInterfaceId | [0]'); sv ENIA $ENIA
  ENIB=$(A ec2 create-network-interface --subnet-id $SUBB --private-ip-address $RT_B_IP --groups $SG \
    --description ee542-router-ethB --tag-specifications "$(tg network-interface routerEthB)" \
    --query NetworkInterface.NetworkInterfaceId); sv ENIB $ENIB
  ATT=$(A ec2 attach-network-interface --network-interface-id $ENIB --instance-id $IRTR --device-index 1 --query AttachmentId)
  A ec2 modify-network-interface-attribute --network-interface-id $ENIB --attachment AttachmentId=$ATT,DeleteOnTermination=true
  A ec2 modify-network-interface-attribute --network-interface-id $ENIA --no-source-dest-check
  A ec2 modify-network-interface-attribute --network-interface-id $ENIB --no-source-dest-check
  EIP=$(A ec2 allocate-address --domain vpc --tag-specifications "$(tg elastic-ip routerEip)" --query AllocationId); sv EIP $EIP
  A ec2 associate-address --allocation-id $EIP --network-interface-id $ENIA >/dev/null
  # force inter-subnet traffic through the router instance (middlebox routing)
  A ec2 create-route --route-table-id $RTA --destination-cidr-block 10.200.2.0/24 --network-interface-id $ENIA >/dev/null
  A ec2 create-route --route-table-id $RTB --destination-cidr-block 10.200.1.0/24 --network-interface-id $ENIB >/dev/null
  echo "ROUTER_OK"
  "$0" ips
  ;;
up)
  "$0" netup && "$0" endpoints && "$0" router
  ;;
ips)
  : ${ICLI:?no state}
  CLIP=$(A ec2 describe-instances --instance-ids $ICLI --query 'Reservations[0].Instances[0].PublicIpAddress')
  SVP=$(A ec2 describe-instances --instance-ids $ISRV --query 'Reservations[0].Instances[0].PublicIpAddress')
  RTP=""
  [ -n "${IRTR:-}" ] && RTP=$(A ec2 describe-instances --instance-ids $IRTR --query 'Reservations[0].Instances[0].PublicIpAddress')
  { echo "CLIENT_PUB=$CLIP"; echo "SERVER_PUB=$SVP"; echo "ROUTER_PUB=$RTP";
    echo "CLIENT_PRIV=$CLI_IP"; echo "SERVER_PRIV=$SRV_IP"; } > "$DIR/hosts.env"
  cat "$DIR/hosts.env"
  ;;
status)
  aws --region $REGION ec2 describe-instances --filters Name=tag:project,Values=ee542-lab2 \
    --query 'Reservations[].Instances[].[Tags[?Key==`Name`]|[0].Value,InstanceId,State.Name,InstanceType,PublicIpAddress,PrivateIpAddress]' \
    --output table
  ;;
stop)  A ec2 stop-instances  --instance-ids $ICLI $ISRV ${IRTR:-} --query 'StoppingInstances[].CurrentState.Name';;
start) A ec2 start-instances --instance-ids $ICLI $ISRV ${IRTR:-} --query 'StartingInstances[].CurrentState.Name'
       A ec2 wait instance-running --instance-ids $ICLI $ISRV ${IRTR:-}; "$0" ips;;
down)
  IDS="${ICLI:-} ${ISRV:-} ${IRTR:-}"; IDS=$(echo $IDS)
  [ -n "$IDS" ] && A ec2 terminate-instances --instance-ids $IDS --query 'TerminatingInstances[].CurrentState.Name'
  [ -n "$IDS" ] && A ec2 wait instance-terminated --instance-ids $IDS
  [ -n "${EIP:-}" ]  && A ec2 release-address --allocation-id $EIP
  A ec2 delete-key-pair --key-name $KEYNAME || true
  [ -n "${SG:-}" ]   && A ec2 delete-security-group --group-id $SG
  # routes must go before subnets/RTs/IGW (a stale IGW/ENI route blocks subnet deletion)
  for RT in "${RTA:-}" "${RTB:-}"; do [ -n "$RT" ] || continue
    for CIDR in 0.0.0.0/0 10.200.1.0/24 10.200.2.0/24; do
      A ec2 delete-route --route-table-id $RT --destination-cidr-block $CIDR 2>/dev/null || true
    done
  done
  [ -n "${IGW:-}" ]  && A ec2 detach-internet-gateway --internet-gateway-id $IGW --vpc-id $VPC 2>/dev/null || true
  [ -n "${SUBA:-}" ] && A ec2 delete-subnet --subnet-id $SUBA
  [ -n "${SUBB:-}" ] && A ec2 delete-subnet --subnet-id $SUBB
  [ -n "${RTA:-}" ]  && A ec2 delete-route-table --route-table-id $RTA
  [ -n "${RTB:-}" ]  && A ec2 delete-route-table --route-table-id $RTB
  [ -n "${IGW:-}" ]  && A ec2 delete-internet-gateway --internet-gateway-id $IGW
  [ -n "${VPC:-}" ]  && A ec2 delete-vpc --vpc-id $VPC
  mv "$STATE" "$STATE.$(date +%s).bak" 2>/dev/null
  rm -f "$DIR/hosts.env"
  echo "DOWN_OK (state backed up)"
  ;;
esac

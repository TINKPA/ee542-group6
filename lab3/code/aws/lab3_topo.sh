#!/bin/bash
# EE542 Lab3 Part 1 -- the handout's four-subnet topology, built with the AWS CLI.
# Separate VPC from the Lab 2 testbed (10.200.0.0/16), which stays up for Part 3.
#
#   VPC 10.0.0.0/16
#     sub1 10.0.1.0/24   client eth0 10.0.1.20   router eth0 10.0.1.10 (EIP)
#     sub2 10.0.2.0/24   server eth0 10.0.2.30   router eth1 10.0.2.10
#     sub3 10.0.3.0/24   client eth1 10.0.3.20 (EIP, SSH only)
#     sub4 10.0.4.0/24   server eth1 10.0.4.30 (EIP, SSH only)
#
# Why four subnets and two NICs per endpoint: the experiment interface (eth0)
# carries the tc impairment the handout asks for (netem delay 100ms loss 10%).
# If SSH rode the same interface, shaping the experiment would shape the control
# channel too -- and re-addressing an EIP-bearing interface kills the session
# outright. eth1 in a separate subnet is the out-of-band management path.
#
# Deviations from the handout, deliberate:
#   - router is Ubuntu + ip_forward, not VyOS: the handout's AMI
#     ami-023863e610a5ee8fe is deregistered, and every VyOS image still published
#     in us-west-2 is an AWS Marketplace product that needs a paid subscription
#     (RunInstances --dry-run returns OptInRequired).
#   - c7i-flex.large, not t2.micro: this account's plan only launches free-tier
#     eligible types, and this keeps the interface naming identical to the Lab 2
#     testbed.  t2.micro itself is allowed (verified by dry-run).
#   - security group allows everything inside 10.0.0.0/16 plus SSH and ICMP from
#     anywhere, instead of the handout's all-TCP/all-UDP from 0.0.0.0/0, which
#     the AWS console itself flags as unsafe.  Same reachability for the lab.
#
# Usage: lab3_topo.sh up | setup | ips | status | stop | start | down
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
STATE="$DIR/lab3_state.env"
export AWS_PAGER=""
REGION=${REGION:-us-west-2}
AZ=${AZ:-us-west-2a}
TYPE=${TYPE:-c7i-flex.large}
KEYNAME=ee542-lab3
CLI0=10.0.1.20; CLI1=10.0.3.20
SRV0=10.0.2.30; SRV1=10.0.4.30
RIP_A=10.0.1.10; RIP_B=10.0.2.10   # router legs; NOT RT0/RT1 -- RT1..RT4 are route-table ids in $STATE
MGW_C=10.0.3.1; MGW_S=10.0.4.1     # VPC gateway of each management subnet (subnet base + 1)

A() { aws --region "$REGION" --output text "$@"; }
sv() { echo "$1=$2" >> "$STATE"; }
tg() { echo "ResourceType=$1,Tags=[{Key=Name,Value=ee542l3-$2},{Key=project,Value=ee542-lab3}]"; }
[ -f "$STATE" ] && . "$STATE"

case "${1:?usage: lab3_topo.sh up|setup|ips|status|stop|start|down}" in
up)
  [ -n "${VPC:-}" ] && { echo "already built ($STATE)"; exit 0; }
  set -e
  VPC=$(A ec2 create-vpc --cidr-block 10.0.0.0/16 --tag-specifications "$(tg vpc vpc)" --query Vpc.VpcId); sv VPC $VPC; echo "VPC=$VPC"
  A ec2 modify-vpc-attribute --vpc-id $VPC --enable-dns-hostnames
  IGW=$(A ec2 create-internet-gateway --tag-specifications "$(tg internet-gateway igw)" --query InternetGateway.InternetGatewayId); sv IGW $IGW
  A ec2 attach-internet-gateway --internet-gateway-id $IGW --vpc-id $VPC
  for N in 1 2 3 4; do
    S=$(A ec2 create-subnet --vpc-id $VPC --cidr-block 10.0.$N.0/24 --availability-zone $AZ --tag-specifications "$(tg subnet sub$N)" --query Subnet.SubnetId); sv SUB$N $S
    R=$(A ec2 create-route-table --vpc-id $VPC --tag-specifications "$(tg route-table rt$N)" --query RouteTable.RouteTableId); sv RT$N $R
    A ec2 associate-route-table --route-table-id $R --subnet-id $S >/dev/null
    A ec2 create-route --route-table-id $R --destination-cidr-block 0.0.0.0/0 --gateway-id $IGW >/dev/null
    echo "sub$N=$S rt$N=$R"
  done
  . "$STATE"
  SG=$(A ec2 create-security-group --group-name ee542-lab3 --description "ee542 lab3" --vpc-id $VPC --tag-specifications "$(tg security-group sg)" --query GroupId); sv SG $SG
  A ec2 authorize-security-group-ingress --group-id $SG --protocol all --cidr 10.0.0.0/16 >/dev/null
  A ec2 authorize-security-group-ingress --group-id $SG --protocol tcp --port 22 --cidr 0.0.0.0/0 >/dev/null
  A ec2 authorize-security-group-ingress --group-id $SG --protocol icmp --port -1 --cidr 0.0.0.0/0 >/dev/null
  A ec2 import-key-pair --key-name $KEYNAME --public-key-material fileb://$HOME/.ssh/id_ed25519.pub >/dev/null 2>&1 || true
  AMI=$(A ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id --query Parameter.Value)
  echo "AMI=$AMI"

  # Each instance gets two ENIs at launch.  eth0 is the experiment interface,
  # eth1 the management interface (client/server) or the second routed leg (router).
  launch() { # $1 name  $2 subnet0  $3 ip0  $4 subnet1  $5 ip1
    # no --security-group-ids here: AWS rejects instance-level groups when
    # --network-interfaces is used; the groups go on each ENI instead.
    A ec2 run-instances --image-id $AMI --instance-type $TYPE --key-name $KEYNAME \
      --tag-specifications "$(tg instance $1)" \
      --network-interfaces "DeviceIndex=0,SubnetId=$2,PrivateIpAddress=$3,Groups=$SG,DeleteOnTermination=true" \
                           "DeviceIndex=1,SubnetId=$4,PrivateIpAddress=$5,Groups=$SG,DeleteOnTermination=true" \
      --query 'Instances[0].InstanceId'
  }
  ICLI=$(launch client $SUB1 $CLI0 $SUB3 $CLI1); sv ICLI $ICLI; echo "client=$ICLI"
  ISRV=$(launch server $SUB2 $SRV0 $SUB4 $SRV1); sv ISRV $ISRV; echo "server=$ISRV"
  IRTR=$(launch router $SUB1 $RIP_A $SUB2 $RIP_B); sv IRTR $IRTR; echo "router=$IRTR"
  A ec2 wait instance-running --instance-ids $ICLI $ISRV $IRTR

  eni() { A ec2 describe-instances --instance-ids $1 \
    --query "Reservations[0].Instances[0].NetworkInterfaces[?Attachment.DeviceIndex==\`$2\`].NetworkInterfaceId | [0]"; }
  CE0=$(eni $ICLI 0); CE1=$(eni $ICLI 1); sv CE0 $CE0; sv CE1 $CE1
  SE0=$(eni $ISRV 0); SE1=$(eni $ISRV 1); sv SE0 $SE0; sv SE1 $SE1
  RE0=$(eni $IRTR 0); RE1=$(eni $IRTR 1); sv RE0 $RE0; sv RE1 $RE1

  # A router forwards packets addressed to other hosts; the per-ENI src/dst
  # filter would drop every one of them.
  A ec2 modify-network-interface-attribute --network-interface-id $RE0 --no-source-dest-check
  A ec2 modify-network-interface-attribute --network-interface-id $RE1 --no-source-dest-check

  # Longest-prefix-match beats the VPC's implicit 10.0.0.0/16 local route, so
  # client<->server traffic cannot bypass the router.
  A ec2 create-route --route-table-id $RT1 --destination-cidr-block 10.0.2.0/24 --network-interface-id $RE0 >/dev/null
  A ec2 create-route --route-table-id $RT2 --destination-cidr-block 10.0.1.0/24 --network-interface-id $RE1 >/dev/null

  # EIPs: client/server on their MANAGEMENT interface, router on eth0.
  for P in "EIPC:$CE1" "EIPS:$SE1" "EIPR:$RE0"; do
    V=${P%%:*}; E=${P##*:}
    ALLOC=$(A ec2 allocate-address --domain vpc --tag-specifications "$(tg elastic-ip $V)" --query AllocationId); sv $V $ALLOC
    A ec2 associate-address --allocation-id $ALLOC --network-interface-id $E >/dev/null
  done
  echo "UP_OK"
  "$0" ips
  ;;
ips)
  : ${EIPC:?no state}
  eip() { A ec2 describe-addresses --allocation-ids $1 --query 'Addresses[0].PublicIp'; }
  { echo "L3_CLIENT_PUB=$(eip $EIPC)"; echo "L3_SERVER_PUB=$(eip $EIPS)"; echo "L3_ROUTER_PUB=$(eip $EIPR)";
    echo "L3_CLIENT_EXP=$CLI0"; echo "L3_SERVER_EXP=$SRV0"; echo "L3_ROUTER_A=$RIP_A"; echo "L3_ROUTER_B=$RIP_B"; } > "$DIR/l3_hosts.env"
  cat "$DIR/l3_hosts.env"
  ;;
setup)
  . "$DIR/l3_hosts.env"
  SSH="ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
  echo "== wait for ssh =="
  for h in $L3_CLIENT_PUB $L3_SERVER_PUB $L3_ROUTER_PUB; do
    for i in $(seq 1 40); do $SSH -o BatchMode=yes ubuntu@$h true 2>/dev/null && break; sleep 5; done
  done
  echo SSH_OK
  # The endpoints have NO public address on their experiment NIC: the EIP sits on
  # the management NIC, and cloud-init still points the main table's default route
  # at eth0.  Outbound packets therefore leave an interface the Internet Gateway
  # has no NAT entry for, and apt hangs with no route to the archive.  Move the
  # default route onto the management NIC; the explicit /24 route added below
  # keeps experiment traffic on eth0 through the router.  (This is the handout's
  # "why can't the VM reach the Internet" question in its four-subnet form.)
  fixdefault() { # $1 = public ip, $2 = mgmt private ip, $3 = mgmt gateway
    $SSH ubuntu@$1 "set -e
      MIF=\$(ip -o -4 addr show | awk '/$2/{print \$2}' | head -1)
      [ -n \"\$MIF\" ] || { echo NO_MGMT_IFACE; exit 1; }
      sudo ip route replace default via $3 dev \$MIF
      echo \"DEFAULT_VIA_MGMT \$MIF\"; ip route | head -3"
  }
  fixdefault $L3_CLIENT_PUB $CLI1 $MGW_C
  fixdefault $L3_SERVER_PUB $SRV1 $MGW_S
  for h in $L3_CLIENT_PUB $L3_SERVER_PUB $L3_ROUTER_PUB; do
    $SSH ubuntu@$h 'set -e
      cloud-init status --wait >/dev/null 2>&1 || true
      sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=180 -qq update
      sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=180 -qq install -y iperf iperf3 >/dev/null 2>&1
      command -v iperf3 >/dev/null || { echo IPERF3_MISSING; exit 1; }
      echo "TOOLS_OK $(hostname -I)"' || { echo "SETUP_FAILED on $h"; exit 1; }
  done
  # Router: both legs must live in the MAIN table, or forwarded packets go back
  # out the default gateway (cloud-init puts a secondary ENI's routes in policy
  # table 101 only -- the failure seen on the Lab 2 testbed).
  $SSH ubuntu@$L3_ROUTER_PUB "
    SEC=\$(ip -o -4 addr show | awk '/$L3_ROUTER_B/{print \$2}' | head -1)
    [ -n \"\$SEC\" ] || { echo NO_SECONDARY_IFACE; exit 1; }
    printf 'network:\n  version: 2\n  ethernets:\n    %s:\n      dhcp4: false\n      dhcp6: false\n      addresses: [$L3_ROUTER_B/24]\n      routes:\n        - to: 10.0.2.0/24\n          scope: link\n' \"\$SEC\" | sudo tee /etc/netplan/60-ethB.yaml >/dev/null
    sudo chmod 600 /etc/netplan/60-ethB.yaml; sudo netplan apply
    echo 'net.ipv4.ip_forward=1' | sudo tee /etc/sysctl.d/99-fwd.conf >/dev/null
    sudo sysctl -qw net.ipv4.ip_forward=1
    echo \"ROUTER_NET_OK sec=\$SEC\"; ip -brief addr show | grep -E '^(en|eth)'"
  # Endpoints: the handout also asks for a guest-side route to the router.
  # The management ENI keeps cloud-init's own policy-routing table, which is what
  # makes SSH replies leave on the interface the request arrived on.
  $SSH ubuntu@$L3_CLIENT_PUB "EXP=\$(ip -o -4 addr show | awk '/$L3_CLIENT_EXP/{print \$2}' | head -1)
    sudo ip route replace 10.0.2.0/24 via $L3_ROUTER_A dev \$EXP; echo \"CLIENT_ROUTE_OK exp=\$EXP\"; ip route | grep 10.0.2"
  $SSH ubuntu@$L3_SERVER_PUB "EXP=\$(ip -o -4 addr show | awk '/$L3_SERVER_EXP/{print \$2}' | head -1)
    sudo ip route replace 10.0.1.0/24 via $L3_ROUTER_B dev \$EXP; echo \"SERVER_ROUTE_OK exp=\$EXP\"; ip route | grep 10.0.1"
  echo "== verify forwarding (expect ttl=63) =="
  $SSH ubuntu@$L3_CLIENT_PUB "ping -c 3 -W 2 $L3_SERVER_EXP"
  echo SETUP_OK
  ;;
status)
  aws --region $REGION ec2 describe-instances --filters Name=tag:project,Values=ee542-lab3 \
    --query 'Reservations[].Instances[].[Tags[?Key==`Name`]|[0].Value,InstanceId,State.Name,PrivateIpAddress]' --output table
  ;;
stop)  A ec2 stop-instances  --instance-ids $ICLI $ISRV $IRTR --query 'StoppingInstances[].CurrentState.Name';;
start) A ec2 start-instances --instance-ids $ICLI $ISRV $IRTR --query 'StartingInstances[].CurrentState.Name'
       A ec2 wait instance-running --instance-ids $ICLI $ISRV $IRTR; "$0" ips;;
down)
  IDS=$(echo "${ICLI:-} ${ISRV:-} ${IRTR:-}")
  if [ -n "$IDS" ]; then
    A ec2 terminate-instances --instance-ids $IDS --query 'TerminatingInstances[].CurrentState.Name'
    A ec2 wait instance-terminated --instance-ids $IDS
  fi
  for V in "${EIPC:-}" "${EIPS:-}" "${EIPR:-}"; do [ -n "$V" ] && A ec2 release-address --allocation-id $V; done
  A ec2 delete-key-pair --key-name $KEYNAME 2>/dev/null || true
  [ -n "${SG:-}" ] && A ec2 delete-security-group --group-id $SG
  for R in "${RT1:-}" "${RT2:-}" "${RT3:-}" "${RT4:-}"; do [ -n "$R" ] || continue
    for C in 0.0.0.0/0 10.0.1.0/24 10.0.2.0/24; do A ec2 delete-route --route-table-id $R --destination-cidr-block $C 2>/dev/null || true; done
  done
  [ -n "${IGW:-}" ] && A ec2 detach-internet-gateway --internet-gateway-id $IGW --vpc-id $VPC 2>/dev/null || true
  for N in 1 2 3 4; do eval "S=\${SUB$N:-}"; [ -n "$S" ] && A ec2 delete-subnet --subnet-id $S; done
  for N in 1 2 3 4; do eval "R=\${RT$N:-}"; [ -n "$R" ] && A ec2 delete-route-table --route-table-id $R; done
  [ -n "${IGW:-}" ] && A ec2 delete-internet-gateway --internet-gateway-id $IGW
  [ -n "${VPC:-}" ] && A ec2 delete-vpc --vpc-id $VPC
  mv "$STATE" "$STATE.$(date +%s).bak" 2>/dev/null
  rm -f "$DIR/l3_hosts.env"
  echo "DOWN_OK"
  ;;
esac

#!/bin/bash
# EE542 Lab2 — 3-node topology in network namespaces (runs INSIDE one Ubuntu VM).
#   cli(10.0.1.2) ─veth─ rtr(10.0.1.1 | 10.0.2.1) ─veth─ srv(10.0.2.2)
# veth supports arbitrary MTU -> the MTU-9000 path UTM's vmnet cannot do.
# Usage: netns_lab.sh setup <mtu> | case <1|2|3> | verify | run <tag> <rate> | teardown
set -u
CMD=${1:?cmd}
U=${SUDO_USER:-$(id -un)}          # run binaries as the invoking user
H=$(eval echo "~$U")               # their home (was hardcoded /home/ubuntu)

nsx() { sudo ip netns exec "$@"; }

case "$CMD" in
setup)
  MTU=${2:?mtu}
  sudo ip netns del cli 2>/dev/null; sudo ip netns del rtr 2>/dev/null; sudo ip netns del srv 2>/dev/null
  for ns in cli rtr srv; do sudo ip netns add $ns; done
  sudo ip link add vc type veth peer name vc-r
  sudo ip link add vs type veth peer name vs-r
  sudo ip link set vc netns cli;  sudo ip link set vc-r netns rtr
  sudo ip link set vs netns srv;  sudo ip link set vs-r netns rtr
  nsx cli ip addr add 10.0.1.2/24 dev vc
  nsx rtr ip addr add 10.0.1.1/24 dev vc-r
  nsx rtr ip addr add 10.0.2.1/24 dev vs-r
  nsx srv ip addr add 10.0.2.2/24 dev vs
  for spec in "cli vc" "rtr vc-r" "rtr vs-r" "srv vs"; do
    set -- $spec; nsx $1 ip link set $2 mtu $MTU; nsx $1 ip link set $2 up; nsx $1 ip link set lo up
  done
  nsx rtr sysctl -qw net.ipv4.ip_forward=1
  nsx cli ip route add 10.0.2.0/24 via 10.0.1.1
  nsx srv ip route add 10.0.1.0/24 via 10.0.2.1
  echo "SETUP_OK mtu=$MTU"
  nsx cli ping -M do -c2 -W2 -s $((MTU-28)) 10.0.2.2 >/dev/null 2>&1 && echo "JUMBO_PING_OK size=$((MTU-28))" || echo "JUMBO_PING_FAIL"
  ;;
case)
  C=${2:?case}
  case $C in
    0) RATE=100mbit; NETEM="delay 0ms";;              # unimpaired: rate-limit verification (~100 Mbps)
    1) RATE=100mbit; NETEM="delay 5ms loss 1%";;
    2) RATE=100mbit; NETEM="delay 100ms loss 20%";;
    3) RATE=80mbit;  NETEM="delay 100ms";;
  esac
  # endpoints: 100mbit egress
  nsx cli tc qdisc del dev vc root 2>/dev/null; nsx srv tc qdisc del dev vs root 2>/dev/null
  nsx cli tc qdisc add dev vc root tbf rate 100mbit latency 0.001ms burst 9015
  nsx srv tc qdisc add dev vs root tbf rate 100mbit latency 0.001ms burst 9015
  # router both ifaces: tbf + netem
  for d in vc-r vs-r; do
    nsx rtr tc qdisc del dev $d root 2>/dev/null
    nsx rtr tc qdisc add dev $d root handle 1:0 tbf rate $RATE latency 0.001ms burst 9015
    nsx rtr tc qdisc add dev $d parent 1:1 handle 10: netem $NETEM
  done
  echo "CASE${C}_SET rate=$RATE netem=[$NETEM]"
  ;;
verify)
  nsx cli ping -i 0.2 -c 50 -q 10.0.2.2 2>&1 | tail -2
  ;;
sec1)
  # Lab §1 "Simulating Networking Environments": iperf TCP+UDP (both directions)
  # + ping verification, for one case. Run `setup <mtu>` then `case <C>` first.
  # Usage: sec1 <0|1|2|3> [dur_s]     case 0 = unimpaired rate-limit check.
  # iperf2 server-report (UDP loss/jitter) is echoed to the client, so client
  # stdout captures both send rate and loss; logs -> /tmp/sec1_c<C>_*.txt.
  C=${2:?case}; DUR=${3:-15}
  OUT=/tmp/sec1_c${C}
  nsx srv pkill -x iperf 2>/dev/null; nsx cli pkill -x iperf 2>/dev/null; sleep 0.3
  nsx srv iperf -s    >/dev/null 2>&1 &     # TCP server, srv ns
  nsx srv iperf -s -u >/dev/null 2>&1 &     # UDP server, srv ns
  nsx cli iperf -s    >/dev/null 2>&1 &     # TCP server, cli ns (for s->c)
  nsx cli iperf -s -u >/dev/null 2>&1 &     # UDP server, cli ns
  sleep 1
  echo "== sec1 case $C : ping =="
  nsx cli ping -i 0.2 -c 50 10.0.2.2 2>&1 | tail -3 | tee ${OUT}_ping.txt
  echo "== TCP c->s ==";  nsx cli iperf -c 10.0.2.2 -t $DUR -i 5           2>&1 | tee ${OUT}_tcp_c2s.txt | tail -1
  echo "== TCP s->c ==";  nsx srv iperf -c 10.0.1.2 -t $DUR -i 5           2>&1 | tee ${OUT}_tcp_s2c.txt | tail -1
  echo "== UDP c->s ==";  nsx cli iperf -u -c 10.0.2.2 -b 100mbit -t $DUR -i 5 2>&1 | tee ${OUT}_udp_c2s.txt | tail -2
  echo "== UDP s->c ==";  nsx srv iperf -u -c 10.0.1.2 -b 100mbit -t $DUR -i 5 2>&1 | tee ${OUT}_udp_s2c.txt | tail -2
  nsx srv pkill -x iperf 2>/dev/null; nsx cli pkill -x iperf 2>/dev/null
  echo "SEC1_C${C}_DONE -> ${OUT}_*.txt"
  ;;
run)
  # run <tag> <rate> <mtu> [method] [file]
  # method: nak (default) | carousel | ack | stopwait — the receiver auto-selects
  # its half from the HELLO, so only the sender is told the method. file lets a
  # method that cannot finish 1GiB (stopwait on a lossy/high-RTT case) run on a
  # smaller input for a steady-state rate.
  TAG=${2:?tag}; RATE=${3:?rate}; MTU=${4:?mtu}; METHOD=${5:-nak}; FILE=${6:-$H/data.bin}
  sudo pkill -x ftr 2>/dev/null; sleep 0.5
  rm -f $H/recv_ns.bin
  nsx srv sudo -u "$U" $H/ftr recv $H/recv_ns.bin --port 6100 \
      > /tmp/ns_recv_${TAG}.log 2>&1 &
  sleep 1
  nsx cli sudo -u "$U" $H/ftr send $FILE 10.0.2.2 --port 6100 \
      --method $METHOD --rate-mbps $RATE --mtu $MTU > /tmp/ns_send_${TAG}.log 2>/tmp/ns_send_${TAG}.err
  sleep 1
  T0=$(grep T_FIRST_BIT_NS /tmp/ns_send_${TAG}.log | awk '{print $2}')
  T1=$(grep T_LAST_BIT_NS /tmp/ns_recv_${TAG}.log | awk '{print $2}')
  RD=$(grep '^ROUNDS' /tmp/ns_send_${TAG}.log | awk '{print $2}')
  PK=$(grep '^TOTAL_PKTS' /tmp/ns_send_${TAG}.log | awk '{print $2}')
  FB=$(stat -c %s "$FILE" 2>/dev/null || echo 0)
  M=$(md5sum $H/recv_ns.bin 2>/dev/null | awk '{print $1}')
  EXP=$(md5sum "$FILE" 2>/dev/null | awk '{print $1}')
  OK=false; [ -n "$EXP" ] && [ "$M" = "$EXP" ] && OK=true
  OW="null"; [ -n "$T0" ] && [ -n "$T1" ] && OW=$(python3 -c "print((int($T1)-int($T0))/1e9)")
  echo "{\"tag\":\"$TAG\",\"method\":\"$METHOD\",\"mtu\":$MTU,\"rate\":$RATE,\"bytes\":$FB,\"oneway_s\":$OW,\"rounds\":${RD:-null},\"total_pkts\":${PK:-null},\"md5_ok\":$OK}" >> $H/runs_netns.jsonl
  echo "[$TAG] method=$METHOD oneway=${OW}s rounds=${RD:-?} pkts=${PK:-?} md5_ok=$OK"
  sync
  ;;
runlt)
  TAG=${2:?tag}; RATE=${3:?rate}; MTU=${4:?mtu}; LOSS=${5:?loss}
  sudo pkill -x ltr 2>/dev/null; sleep 0.5
  rm -f $H/recv_lt.bin
  nsx srv sudo -u "$U" $H/ltr recv $H/recv_lt.bin --port 6200 \
      > /tmp/lt_recv_${TAG}.log 2>&1 &
  sleep 1
  nsx cli sudo -u "$U" $H/ltr send $H/data.bin 10.0.2.2 --port 6200 \
      --rate-mbps $RATE --mtu $MTU --loss $LOSS > /tmp/lt_send_${TAG}.log 2>/tmp/lt_send_${TAG}.err
  sleep 1
  T0=$(grep T_FIRST_BIT_NS /tmp/lt_send_${TAG}.log | awk '{print $2}')
  T1=$(grep T_LAST_BIT_NS /tmp/lt_recv_${TAG}.log | awk '{print $2}')
  PK=$(grep '^TOTAL_PKTS' /tmp/lt_send_${TAG}.log | awk '{print $2}')
  M=$(md5sum $H/recv_lt.bin 2>/dev/null | awk '{print $1}')
  EXP=$(cat $H/data.md5 2>/dev/null)
  OK=false; [ -n "$EXP" ] && [ "$M" = "$EXP" ] && OK=true
  OW="null"; [ -n "$T0" ] && [ -n "$T1" ] && OW=$(python3 -c "print((int($T1)-int($T0))/1e9)")
  echo "{\"tag\":\"$TAG\",\"proto\":\"lt\",\"mtu\":$MTU,\"rate\":$RATE,\"loss\":$LOSS,\"oneway_s\":$OW,\"total_pkts\":${PK:-null},\"md5_ok\":$OK}" >> $H/runs_lt.jsonl
  echo "[$TAG] oneway=${OW}s pkts=${PK:-?} md5_ok=$OK"
  sync
  ;;
teardown)
  sudo ip netns del cli 2>/dev/null; sudo ip netns del rtr 2>/dev/null; sudo ip netns del srv 2>/dev/null
  echo TORNDOWN
  ;;
esac

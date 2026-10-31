#!/usr/bin/env bash
# EE542 Lab 8 Part 7: why does write bandwidth dip around 64 KB? One ib_write_bw
# per message size, with the NIC drop/retransmit counters before and after.
# Runs on the Mac after sourcing data/raw/part7_hosts.env.
#   ./dip_probe.sh 3 > ../../data/raw/part7_dip_probe.log
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
rounds="${1:-3}"
snap='source ~/lab8/code/part7/env.sh
d=/sys/class/infiniband/$RDEV/ports/1/hw_counters
echo rx_discards_phy=$(sudo ethtool -S $NETDEV | awk "/rx_discards_phy/{print \$2}") tx_global_pause=$(sudo ethtool -S $NETDEV | awk "/tx_global_pause:/{print \$2}") out_of_sequence=$(cat $d/out_of_sequence) packet_seq_err=$(cat $d/packet_seq_err) np_cnp_sent=$(cat $d/np_cnp_sent) rp_cnp_handled=$(cat $d/rp_cnp_handled)'
echo "size round bw_avg_gbps node0_before node0_after node1_before node1_after"
for r in $(seq 1 "$rounds"); do
  for s in 16384 32768 65536 131072 262144 1048576; do
    a0=$("$here/cl.sh" 0 "$snap" | tail -1); a1=$("$here/cl.sh" 1 "$snap" | tail -1)
    "$here/cl.sh" 0 "source ~/lab8/code/part7/env.sh; nohup ib_write_bw -d \$RDEV -x 3 --report_gbits -s $s >/tmp/part7_dip_srv.log 2>&1 < /dev/null &"
    sleep 2
    bw=$("$here/cl.sh" 1 "source ~/lab8/code/part7/env.sh; ib_write_bw -d \$RDEV -x 3 --report_gbits -s $s 10.10.1.1 2>&1" | awk -v s="$s" '$1==s && NF>=5{print $4}' | tail -1)
    sleep 1
    b0=$("$here/cl.sh" 0 "$snap" | tail -1); b1=$("$here/cl.sh" 1 "$snap" | tail -1)
    echo "$s $r ${bw:-NA} | $a0 | $b0 | $a1 | $b1"
  done
done

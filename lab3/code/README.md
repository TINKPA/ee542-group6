# EE 542 Lab 3 — AWS tutorial and TCP congestion control

Due **Saturday Sep 19, 2026**. Group of 3.

Everything here runs from a Mac against EC2 over `ssh`; no script needs to be
copied to a node by hand.

## Two testbeds

Lab 3 uses two independent VPCs, because Part 1 and Part 3 want different things
from the topology.

| Used for | Script | VPC | Shape |
|---|---|---|---|
| Part 1 tutorial | `aws/lab3_topo.sh` | `10.0.0.0/16` | the handout's four subnets, two NICs per endpoint |
| Part 2 / Part 3 | `../../lab2/code/aws/aws_lab.sh` | `10.200.0.0/16` | the Lab 2 three-node chain |

The four-subnet design exists because Part 1 asks for `netem` on the endpoint's
own interface. If SSH rode that interface, shaping the experiment would shape the
control channel, and re-addressing an interface that carries an Elastic IP kills
the session outright. So each endpoint gets a second ENI in its own subnet as an
out-of-band management path, and the Elastic IP lives there.

Forwarding through the router is proved the same way in both: `ttl=63`.

## Layout

```
aws/lab3_topo.sh        four-subnet topology: up | setup | ips | status | stop | start | down
part1_tc_steps.sh       the handout's tc sequence (delay, loss, tbf) with iperf3 at each step
part1_tc_location.sh    the same sequence applied at three places, endpoint vs router
scp_sweep.sh            baseline | full | sweep | cell -- scp goodput over RTT x loss
kmod/ee542_cc.c         the loadable congestion control (registers ee542 and ee542c)
kmod/deploy.sh          build, load and hard-verify the module on the client
kernel/kbuild.sh        disposable build host for the patched kernel
kernel/apply_patch.py   applies no_backoff.patch to a fresh linux-aws tree
kernel/no_backoff.patch the RTO-backoff removal, exposed as a sysctl
kernel/install_client.sh install the built kernel on the client and reboot into it
kernel/matrix.sh        the 2x2 "test each modification separately and combined" grid
```

## Part 3 in three steps

**1. The module.** Congestion control is pluggable
(`struct tcp_congestion_ops`), so removing the window reduction needs no kernel
build, only `linux-headers` for the running kernel:

```bash
./kmod/deploy.sh
ssh ubuntu@<client> "sudo sysctl -w net.ipv4.tcp_congestion_control=ee542c"
```

One `.ko` registers two algorithms that differ only in which hook does the
pinning, `cong_avoid()` for `ee542` and `cong_control()` for `ee542c`. Switching
is then a sysctl write, which matters because `rmmod` is unreliable here: the
per-netns default congestion control holds a module reference.

**2. The kernel.** The RTO backoff is in `tcp_retransmit_timer()`, compiled into
`vmlinux`, so it does need a build:

```bash
./kernel/kbuild.sh up && ./kernel/kbuild.sh lsmod && ./kernel/kbuild.sh src
./kernel/kbuild.sh build && ./kernel/kbuild.sh fetch && ./kernel/kbuild.sh testboot
./kernel/install_client.sh
```

The patch adds `net.ipv4.tcp_no_rto_backoff` rather than hard-coding the new
behaviour, so both arms of the comparison run on one kernel binary and one boot.

`make localmodconfig` against the target node's own `lsmod` is what makes a
2-vCPU build finish in 31 minutes instead of the handout's 10 hours. It has one
trap: `inet_diag` is built into stock Ubuntu kernels and therefore never appears
in `lsmod`, so `localmodconfig` drops it, and `ss` then silently falls back to
parsing `/proc/net/tcp` with no `bytes_sent`, no `bytes_retrans` and no `rtt`.
`kbuild.sh` re-enables it explicitly.

**3. Measure.**

```bash
CC=ee542c ./scp_sweep.sh sweep 60
CC=ee542c ./scp_sweep.sh full 200 20
./kernel/matrix.sh 120
```

## Reproducing a number

Every result in the report comes from one of these scripts, and every script
writes to `../data/raw/<name>/` with the parameters in the filename. The CSVs
there are the exact inputs to the plotting scripts in `../data/`.

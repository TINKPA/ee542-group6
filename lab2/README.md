# EE 542 Lab 2 - Fast, Reliable File Transfer

Due **Saturday Sep 5, 2026**. Group of 3.

## Topology

Carried forward from Lab 1. The handout assumes `eth0`/`eth1` and
`10.200.x.0/24`; we keep our working addressing and note the mapping.

| Role | Machine | Interface | Address | Handout calls it |
|---|---|---|---|---|
| Server | Ubuntu VM | `ens33` | 192.168.10.100 | server |
| Client | Ubuntu VM | `ens33` | 192.168.20.100 | client |
| Router | VyOS | `eth1` | 192.168.10.1 | eth0 |
| Router | VyOS | `eth2` | 192.168.20.1 | eth1 |

## Lanes

| Owner | Lane | Directories |
|---|---|---|
| TBD | Bench + harness + critical thinking writeup | `scripts/`, `bench/` |
| TBD | Transport methods (sender + receiver per method) | `src/methods/` |
| TBD | Shared chassis: framing, pacing, bitmap, session | `src/common.hpp` |

## Code: one binary, several methods

`src/` builds a single `ftr` binary that hosts several transfer methods on one
paced-UDP chassis. A **method** is a matched (sender, receiver) pair; the only
thing that differs between them is how the set of blocks still to send is
narrowed. The receiver reads the method from the sender's HELLO and dispatches
its own half, so the two ends can never be misconfigured.

| Method | What it deletes / adds | Role |
|---|---|---|
| `nak` | paced blast + per-round batched NAK | **our protocol** (the paper) |
| `carousel` | loops the whole file, no feedback but a final DONE | baseline: pipe full, retransmit maximally blind |
| `ack` | per-packet ACK, drop acked blocks; effectively infinite window | baseline: naive "big-window TCP" over UDP |
| `stopwait` | window = 1: send one, wait one ACK, timeout-resend | baseline: correct but no pipelining |

```bash
cd src && make                      # builds ./ftr
./ftr recv out.bin --port 5555                          # receiver (auto-detects method)
./ftr send data.bin <ip> --method nak      --port 5555  # our protocol
./ftr send data.bin <ip> --method carousel --port 5555  # a baseline
./ftr send data.bin <ip> --method ack      --port 5555
./ftr send data.bin <ip> --method stopwait --port 5555
```

Correctness of all methods (byte-exact delivery under simulated loss, incl.
MTU 9000) is checked on loopback by `bench/smoke_loopback.sh`. Real per-case
throughput is gathered with `bench/netns_lab.sh` / `bench/netns_matrix.sh`
(one VM, veth/netns three-node topology) or the VyOS/VM `scripts/` bench.

> **Wire-format note (needs a group decision).** The shipped code uses the
> 8-byte header in `src/common.hpp` (1464 B payload at MTU 1500, matching the
> report). `include/protocol.h` holds an earlier, richer frozen contract
> (16-byte header, session ids) that was never implemented. They diverge;
> reconciling them is left to the group and is deliberately **not** done
> unilaterally here.

## Bench operating order

Every measurement run follows this sequence. Do not skip step 4.

```bash
# 1. Router: apply the case
sudo ./scripts/apply-case.sh 2

# 2. Both endpoints: shape egress to 100mbit
sudo DEV=ens33 ./scripts/node-shape.sh apply

# 3. All three machines: set MTU (router needs DEVS="eth1 eth2")
sudo ./scripts/set-mtu.sh 1500

# 4. Endpoint: prove the bench matches the case before recording anything
PEER=192.168.10.100 ./scripts/verify.sh 2

# 5. Only if step 4 printed PASS, run the transfer.
```

`verify.sh` exits nonzero on failure and writes raw ping/iperf output plus a
`summary.txt` to `~/lab2-results/caseN-<timestamp>/`. Those files are report
evidence - keep them.

## Test matrix - 6 mandatory runs

Each moves 1 GB and must end with matching md5 on both sides.

| | MTU 1500 | MTU 9001 |
|---|---|---|
| Case 1 - RTT 10ms, 1% loss, 100mbit | | |
| Case 2 - RTT 200ms, 20% loss, 100mbit | | |
| Case 3 - RTT 200ms, no loss, 80mbit | | |

Competitive floor: **20 Mbps**. Timing is first bit out of the sender to last
bit into the receiver.

## Test file

```bash
dd if=/dev/urandom of=data.bin bs=1M count=1024
md5sum data.bin | tee data.bin.md5
```

## Open questions for the TA

1. MTU **9000** (page 1) or **9001** (pages 5 and 6)? Using 9001.
2. Direction: page 5 says client sends to server, then says the server sends
   and the client saves. Supporting both, invoked scp-style.
3. "Lab3 of scp part" on page 4 - assumed to mean Lab 1.

## Submission checklist

- [ ] One edited YouTube video, stitched from daily phone clips
- [ ] Daily clips: every member on camera, what they did, what broke, the fix
- [ ] Screen footage recorded **by phone**, not a capture tool
- [ ] GitHub repo with descriptive commits, logs included in submission
- [ ] PDF with the YouTube link and the git logs
- [ ] Report: concept, results, **flow chart**, **data structures**, **algorithm**, analysis
- [ ] Source files

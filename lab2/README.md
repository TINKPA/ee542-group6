# EE 542 Lab 2 - Fast, Reliable File Transfer

Due **Saturday Sep 5, 2026**. Group of 3.

Move a 1 GB file one way, with zero errors, as fast as possible, over three
impaired links. Reliability is a pass/fail gate (matching md5 on both ends);
speed is the competitive metric, floor 20 Mbps.

## Topology

Carried forward from Lab 1. The handout assumes `eth0`/`eth1` and
`10.200.x.0/24`; we keep our working addressing and note the mapping.

| Role | Machine | Interface | Address | Handout calls it |
|---|---|---|---|---|
| Server | Ubuntu VM | `ens33` | 192.168.10.100 | server |
| Client | Ubuntu VM | `ens33` | 192.168.20.100 | client |
| Router | VyOS | `eth1` | 192.168.10.1 | eth0 |
| Router | VyOS | `eth2` | 192.168.20.1 | eth1 |

## Test file

```bash
dd if=/dev/urandom of=data.bin bs=1M count=1024
md5sum data.bin | tee data.bin.md5
```
Every run must end with this md5 matching on both ends.

## Section 1 - what the impaired links do

| Condition | RTT | UDP | TCP |
|---|---|---|---|
| Case 1 - 10 ms, 1% loss | ~11.6 ms | 100 Mbps | 17.3 Mbps |
| Case 2 - 200 ms, 20% loss | ~201 ms | 77.8 Mbps | **0.19 Mbps** |
| Case 3 - 200 ms, 80 mbit cap | ~201 ms | 77.8 Mbps | 65.7 Mbps |

Cases 2 and 3 deliver identical UDP throughput but differ ~450x for TCP. That
gap is what our protocol exists to close.

## Measurement methodology

- One-way time is sender first-bit to receiver last-bit, corrected by a
  measured client/server clock offset (midpoint of a best-of-5 RTT bracket).
- tbf `burst` must hold at least one full frame or pacing jitter becomes loss;
  this dominates the MTU-9000 result (see below).
- The testbed adds 5-15% inherent loss on top of netem; effective loss p_eff
  reaches ~0.29 in Case 2. Every run still converged and passed md5.

## Robustness

A dropped NAK part is not fatal: the sender only advances a round once it has a
complete missing-set, and any still-missing block simply rolls into the next
round. Reliability is structural - the transfer ends only when the bitmap is
full - so loss rate affects speed, never correctness.

Verified across 21 runs (9 three-VM + 12 netns): every transfer converged and
passed md5, with no rate tuning across cases.

## MTU 1500 vs 9000

Jumbo frames run on the netns testbed (vmnet rejects >1500). They come out
~30% *slower*, all md5-verified.

The cause is configuration, not frame size: the shaper's `burst` held exactly
one 9000 B frame, leaving zero buffer, so any pacing jitter became loss. The
lesson is that shaper burst must scale with MTU.
A scaled-burst control run would confirm it directly.

## Headline results (1 GiB, 3 reps/case, md5-verified both ends)

| Case | Link | scp (TCP) | Ours (median) | Goodput |
|---|---|---|---|---|
| 1 | 100M / 10ms / 1% | 973 s | **115 s** | 74.5 Mbps |
| 2 | 100M / 200ms / 20% | ~15 d | **135 s** | 63.7 Mbps |
| 3 | 80M / 200ms / 0% | 346 s | **125 s** | 69.0 Mbps |

## Design by deletion

The link is dedicated and fully known, so each classical mechanism can go:
congestion control (no competing flows), slow start (rate known), backoff
(loss is random, not congestion). What remains is pace-at-line-rate + retransmit
only what the bitmap says is missing.

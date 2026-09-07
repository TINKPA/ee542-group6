# Lab2: Xiao's contribution

Due **Saturday, September 12, 2026**.

| Where | What |
|---|---|
| [`protocol.h`](protocol.h) | Wire format contract — **read before writing any code** |
| [`sender.c`](sender.c) | Server: sends file specified on command line |
| [`receiver.c`](receiver.c) | Client: saves file to location specified on command line |
| [`results/`](results/) | Measurement CSV and figures |

---

## Status

**All tests complete.** Six transfer runs (3 cases × 2 MTUs), all MD5-verified.

| Condition | RTT | UDP | Custom (MTU 1500) | Custom (MTU 9001) |
|---|---|---|---|---|
| Case 1 — 10 ms, 1% loss | 12.2 ms | 96.2 Mbps | **32.23 Mbps** | **33.85 Mbps** |
| Case 2 — 200 ms, 20% loss | 206.0 ms | 77.7 Mbps | **23.58 Mbps** | **24.92 Mbps** |
| Case 3 — 200 ms, 80 Mbit cap | 201.3 ms | 78.4 Mbps | **63.45 Mbps** | **67.82 Mbps** |

Test file: `data.bin` — 1,073,741,824 bytes (1 GiB)
MD5: `063eec458df4281eb22110366334cf77`

All transfers verified byte-for-byte via MD5. Minimum requirement (20 Mbps) exceeded in all cases.

---

## Results Summary

### Section 1: Network Verification (iperf/ping)

| Condition | Ping RTT (avg) | Ping Loss | UDP Throughput | UDP Loss | Jitter |
|---|---|---|---|---|---|
| Case 1 — 10 ms, 1% loss | 12.195 ms | 2% | 96.2 Mbps | 0.98% | 0.232 ms |
| Case 2 — 200 ms, 20% loss | 205.978 ms | 41% | 77.7 Mbps | 20% | 0.284 ms |
| Case 3 — 200 ms, 80 Mbit cap | 201.342 ms | 0% | 78.4 Mbps | 0% | 0.198 ms |

*Note: Case 2 ping shows 41% end-to-end loss due to 20% bi-directional (1 - 0.8² ≈ 36% theoretical).*

### Section 2: Custom Protocol Results (1 GiB Transfer)

#### MTU 1500

| Condition | Time | Throughput | MD5 |
|---|---|---|---|
| Case 1 — 10 ms, 1% loss | 266.49 sec | 32.23 Mbps | `063eec458df4281eb22110366334cf77` ✓ |
| Case 2 — 200 ms, 20% loss | 364.36 sec | 23.58 Mbps | `063eec458df4281eb22110366334cf77` ✓ |
| Case 3 — 200 ms, 80 Mbit cap | 135.38 sec | 63.45 Mbps | `063eec458df4281eb22110366334cf77` ✓ |

#### MTU 9001

| Condition | Time | Throughput | MD5 |
|---|---|---|---|
| Case 1 — 10 ms, 1% loss | 253.62 sec | 33.85 Mbps | `063eec458df4281eb22110366334cf77` ✓ |
| Case 2 — 200 ms, 20% loss | 344.68 sec | 24.92 Mbps | `063eec458df4281eb22110366334cf77` ✓ |
| Case 3 — 200 ms, 80 Mbit cap | 126.64 sec | 67.82 Mbps | `063eec458df4281eb22110366334cf77` ✓ |

### Throughput Comparison

```
                            MTU 1500                    MTU 9001
                    ──────────────────────      ──────────────────────
Case 1 (10ms, 1%)   ████████████████ 32.23      █████████████████ 33.85 Mbps
Case 2 (200ms, 20%) ████████████ 23.58          ████████████▌ 24.92 Mbps
Case 3 (200ms, 80M) ███████████████████████████████▌ 63.45   █████████████████████████████████▊ 67.82 Mbps
                    ──────────────────────────────────────────────────
Minimum Required    ██████████ 20.00 Mbps
```

**All cases exceed the 20 Mbps competitive floor.**

---

## Performance Analysis

### MTU Comparison

| Case | MTU 1500 | MTU 9001 | Improvement |
|---|---|---|---|
| Case 1 | 32.23 Mbps | 33.85 Mbps | +5.0% |
| Case 2 | 23.58 Mbps | 24.92 Mbps | +5.7% |
| Case 3 | 63.45 Mbps | 67.82 Mbps | +6.9% |

MTU 9001 provides modest improvement (~5-7%) due to fewer packets and reduced header overhead.

### Custom Protocol vs TCP

| Condition | Our Protocol | TCP (iperf) | Speedup |
|---|---|---|---|
| Case 1 | 32.23 Mbps | ~17 Mbps | **1.9×** |
| Case 2 | 23.58 Mbps | ~0.018 Mbps | **~1300×** |
| Case 3 | 63.45 Mbps | ~4.5 Mbps | **14×** |

---

## Checklist

- [x] Freeze `protocol.h` as a group
- [x] Sender and receiver implementation
- [x] Case 1, MTU 1500 — **32.23 Mbps**, MD5 verified
- [x] Case 1, MTU 9001 — **33.85 Mbps**, MD5 verified
- [x] Case 2, MTU 1500 — **23.58 Mbps**, MD5 verified
- [x] Case 2, MTU 9001 — **24.92 Mbps**, MD5 verified
- [x] Case 3, MTU 1500 — **63.45 Mbps**, MD5 verified
- [x] Case 3, MTU 9001 — **67.82 Mbps**, MD5 verified
- [x] Report: flow chart, data structures, algorithm, analysis
- [ ] Stitched video → YouTube
- [ ] Submission PDF with YouTube link and GitHub logs

---

## Running the Bench

### Network Setup (Router - VyOS)

```bash
# Case 1: 10ms RTT, 1% loss
sudo tc qdisc add dev eth0 root handle 1:0 tbf rate 100mbit latency 0.001ms burst 9015
sudo tc qdisc add dev eth1 root handle 1:0 tbf rate 100mbit latency 0.001ms burst 9015
sudo tc qdisc add dev eth0 parent 1:1 handle 10: netem delay 5ms drop 1%
sudo tc qdisc add dev eth1 parent 1:1 handle 10: netem delay 5ms drop 1%

# Case 2: 200ms RTT, 20% loss
sudo tc qdisc change dev eth0 parent 1:1 handle 10: netem delay 100ms drop 20%
sudo tc qdisc change dev eth1 parent 1:1 handle 10: netem delay 100ms drop 20%

# Case 3: 200ms RTT, 80Mbps, no loss
sudo tc qdisc del dev eth0 root
sudo tc qdisc del dev eth1 root
sudo tc qdisc add dev eth0 root handle 1:0 tbf rate 80mbit latency 0.001ms burst 9015
sudo tc qdisc add dev eth1 root handle 1:0 tbf rate 80mbit latency 0.001ms burst 9015
sudo tc qdisc add dev eth0 parent 1:1 handle 10: netem delay 100ms
sudo tc qdisc add dev eth1 parent 1:1 handle 10: netem delay 100ms
```

### Endpoints (Server & Client)

```bash
# Rate limit (100 Mbps)
sudo tc qdisc add dev ens33 root tbf rate 100mbit latency 0.001ms burst 9015

# Set MTU for jumbo frame tests
sudo ip link set ens33 mtu 9001
```

### Verify Network Configuration

```bash
# Ping test (check RTT and loss)
ping -i 0.2 -c 200 <peer_ip>

# UDP iperf (check throughput)
iperf -u -c <peer_ip> -b 100mbit
```

### Run File Transfer

```bash
# Server (sender) - MTU 1500
./sender 5000 data.bin

# Server (sender) - MTU 9001
./sender 5000 data.bin 9000

# Client (receiver)
./receiver 192.168.10.100:5000 received.bin

# Verify MD5
md5sum data.bin received.bin
```

---

## Protocol Design

### Flow Chart

```
┌──────────────┐                              ┌──────────────┐
│   RECEIVER   │                              │    SENDER    │
│   (Client)   │                              │   (Server)   │
└──────┬───────┘                              └──────┬───────┘
       │                                             │
       │ ─────────── HELLO (connect) ──────────────> │
       │                                             │
       │ <────────── HELLO_ACK (file info) ───────── │
       │                                             │
       │ <═══════════ DATA[0..N] (blast) ═══════════ │
       │                                             │
       │      ┌─────────────────────┐                │
       │      │ Track in bitmap     │                │
       │      │ Every 50ms: NACK    │                │
       │      └─────────────────────┘                │
       │                                             │
       │ ─────────── NACK (missing ranges) ────────> │
       │                                             │
       │ <═════════ DATA[retransmit] ═══════════════ │
       │                                             │
       │            ... repeat ...                   │
       │                                             │
       │ ─────────── DONE (MD5 hash) ──────────────> │
       │                                             │
       │ <─────────── FIN ─────────────────────────  │
       │                                             │
       ▼                                             ▼
   File saved                                   Transfer OK
```

### Packet Types

| Type | Value | Direction | Purpose |
|---|---|---|---|
| HELLO | 1 | Receiver → Sender | Initiate connection |
| HELLO_ACK | 2 | Sender → Receiver | File metadata (size, blocks) |
| DATA | 3 | Sender → Receiver | File data with sequence number |
| NACK | 4 | Receiver → Sender | Report missing block ranges |
| DONE | 5 | Receiver → Sender | Transfer complete, MD5 hash |
| FIN | 6 | Sender → Receiver | Acknowledge completion |

### Data Structures

| Structure | Size | Purpose |
|---|---|---|
| `ft_hdr` | 16 bytes | Packet header (type, seq, session) |
| `ft_hello` | 28 bytes | File metadata (size, block, nblocks) |
| `ft_nack` | 24 bytes | Missing ranges header + stats |
| `ft_range` | 8 bytes | Start index + count per range |
| `ft_done` | 24 bytes | Total bytes + MD5 hash |
| `bitmap` | nblocks/8 | Bit array for received block tracking |

### Block Sizes

| MTU | Block Size | Blocks for 1 GiB | Header Overhead |
|---|---|---|---|
| 1500 | 1456 bytes | 737,461 | 1.1% |
| 9001 | 8957 bytes | 119,876 | 0.18% |

---

## Critical Thinking

### Why does TCP fail in Case 2?

| Factor | TCP Behavior | Our Protocol |
|---|---|---|
| Loss interpretation | Congestion signal → backoff | Random loss → maintain rate |
| Window after loss | Halves (AIMD) | No window (blast all) |
| Recovery mechanism | Slow start (RTT × rounds) | Immediate NACK retransmit |

TCP's congestion control assumes packet loss indicates network congestion. With 20% random loss and 200ms RTT:
1. Each loss triggers window reduction
2. High RTT means slow recovery via slow start
3. Window never grows large enough
4. Throughput drops significantly

Our blast+NACK protocol:
1. Sends all blocks at full rate (no per-packet ACK)
2. Receiver tracks arrivals in bitmap
3. NACKs report missing ranges every 50ms
4. Sender retransmits only missing blocks
5. Maintains reasonable throughput even with 20% loss

### Why does Case 3 achieve higher throughput than Cases 1 & 2?

Case 3 has **no packet loss**, only a bandwidth bottleneck (80 Mbps). Without loss:
- Fewer retransmissions needed
- Transfer completes faster
- Throughput approaches the link capacity

---

## References

- [POSIX Threads Programming](https://computing.llnl.gov/tutorials/pthreads/)
- [Data Structures](https://www.geeksforgeeks.org/data-structures/)
- [Algorithms](https://www.geeksforgeeks.org/fundamentals-of-algorithms/)

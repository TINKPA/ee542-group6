# ee542-group6

USC EE542 Fall 2026 — Group 6 lab assignments

## 📹 Video logs — upload here

**https://drive.google.com/drive/folders/1bIOpWOKy5Rc0xWSo0WjWOQLvE1GoMD-o?usp=sharing**

**Log in with your USC account** to access the folder, then upload your daily
video log there.

---

## Lab 2 — Fast, Reliable File Transfer

Due **Saturday, September 5, 2026**.

| Where | What |
|---|---|
| [`lab2/README.md`](lab2/README.md) | Topology, lane assignments, bench operating order |
| [`lab2/include/protocol.h`](lab2/include/protocol.h) | Wire format contract — **read before writing any code** |
| [`lab2/scripts/`](lab2/scripts/) | Bench automation: apply a case, shape a node, set MTU, verify |
| [`lab2/results/`](lab2/results/) | Consolidated measurement CSV and figures |

### Status

**Section 1 (network emulation) is complete at MTU 1500.** All three mandatory
cases applied and verified in both directions, with saved evidence.

| Condition | RTT | UDP | TCP |
|---|---|---|---|
| Baseline | ~0.5 ms | 94.2 Mbps | 95.6 Mbps |
| Case 1 — 10 ms, 1% loss | 11.6 ms | 100.0 Mbps | 17.3 Mbps |
| Case 2 — 200 ms, 20% loss | 201.7 ms | 77.8 Mbps | **0.19 Mbps** |
| Case 3 — 200 ms, 80 Mbit cap | 201.6 ms | 77.8 Mbps | 65.70 Mbps |

Cases 2 and 3 deliver identical UDP throughput but differ by ~450× for TCP.
That gap is what our protocol exists to close. Per-run figures are in
[`lab2/results/section1-all-runs.csv`](lab2/results/section1-all-runs.csv).

### Remaining

- [ ] Freeze `protocol.h` as a group
- [ ] Sender and receiver implementation
- [ ] Six transfer runs: 3 cases × MTU 1500 and 9001, md5-verified
- [ ] Section 1 verification repeated at MTU 9001
- [ ] Report: flow chart, data structures, algorithm, analysis
- [ ] Stitched video → YouTube, and submission PDF with the link and git logs

Competitive floor is **20 Mbps**. The network carries ~78 Mbps, so that is the
real target.

### Running the bench

```bash
# router
sudo BURST=64000 ~/apply-case.sh 1|2|3

# both endpoints
sudo DEV=ens33 BURST=64000 ~/ee542-group6/lab2/scripts/node-shape.sh apply

# from either endpoint — must PASS before any number is recorded
PEER=<other_host> ~/ee542-group6/lab2/scripts/verify.sh 1|2|3
```

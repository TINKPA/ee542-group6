# EE 542 Lab 3 — AWS testbed and TCP congestion-control modification

**Demo video:** https://youtu.be/yAZhhl6Fp6I

**Report:** [`EE542_Lab3_Report.pdf`](EE542_Lab3_Report.pdf) — *The Bottleneck Moves: Removing TCP's Loss Response on a Known-Lossy Link* (its title block links the video log, https://youtu.be/VVgTWcPTWM4).

## What is here

| | |
|---|---|
| [`code/`](code/README.md) | testbed scripts, the congestion-control module (`kmod/`), the kernel patch (`kernel/`), and the measurement drivers |
| [`data/`](data/) | raw samples behind every figure (`data/raw/`) and the plotting scripts |

`code/README.md` explains the two testbeds and how to reproduce each number.

## Summary

On the handout's network — 100 Mbps, 200 ms RTT, 20 % loss in each direction — stock TCP (cubic) moves a 1 GiB file by scp at 0.07 Mbps. We remove TCP's two responses to loss and measure each separately:

- **Congestion control that does not read loss as congestion** (`code/kmod/ee542_cc.c`, a loadable module, no kernel rebuild): the window is held at the bandwidth-delay product and never reduced on loss. A complete, MD5-verified 1 GiB scp reaches **10.75 Mbps**, and 61 of the 66 cells of the RTT × loss grid exceed 10 Mbps (stock: 12). Which kernel hook does the pinning is worth a factor of two: `cong_avoid()` is never reached while the connection is in recovery, `cong_control()` is.
- **Exponential RTO back-off removed** (`code/kernel/no_backoff.patch`, exposed as `net.ipv4.tcp_no_rto_backoff` on a patched kernel, so both arms run on one binary): visible in the timer — the RTO no longer climbs to Linux's 120 s cap — but no change in goodput at this operating point, because the sender is application-limited once the window is released. A raw TCP stream with no application window reaches 37.8 Mbps on the same kernel.

Part 1 (the AWS tutorial and the `tc` experiments) and Part 2 (the Lab 2 paced-UDP protocol on EC2) are in the report's appendices; their scripts and data are under `code/` and `data/raw/`.

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

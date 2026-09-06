#!/usr/bin/env python3
"""Summarize AWS runs.jsonl -> per (case, mtu, rate) med/lo/hi + printed table.
Usage: uv run aws_summarize.py [runs.jsonl] [out.json]
Sweep rows (rep=9) are excluded from headline groups but printed separately."""
import json, statistics, sys
src = sys.argv[1] if len(sys.argv) > 1 else "results/runs.jsonl"
out = sys.argv[2] if len(sys.argv) > 2 else None
rows = [json.loads(l) for l in open(src) if l.strip()]
rows = [r for r in rows if r.get("topo") == "3node" and r["proto"] == "ftr"]
groups, sweep = {}, []
for r in rows:
    (sweep if r["rep"] == 9 else groups.setdefault((r["case"], r["mtu"], r["rate"]), [])).append(r)
F = 8589.934592  # 1 GiB in Mbit
summ = {}
print(f"{'case':>4} {'mtu':>5} {'rate':>5} {'n':>2} {'med_s':>8} {'lo':>8} {'hi':>8} {'Mbps':>6} {'md5':>4}")
for k in sorted(groups):
    g = groups[k]; ts = sorted(x["oneway_s"] for x in g)
    med = statistics.median(ts)
    ok = all(x["md5_ok"] for x in g)
    summ[f"c{k[0]}_m{k[1]}_r{k[2]}"] = {"med": med, "lo": ts[0], "hi": ts[-1], "n": len(ts), "md5_all": ok}
    print(f"{k[0]:>4} {k[1]:>5} {k[2]:>5} {len(ts):>2} {med:>8.2f} {ts[0]:>8.2f} {ts[-1]:>8.2f} {F/med:>6.2f} {'OK' if ok else 'FAIL':>4}")
print("\nsweep (case2/1500):")
for r in sorted(sweep, key=lambda x: x["rate"]):
    print(f"  rate {r['rate']:>5} -> {r['oneway_s']:>8.2f} s  {r['mbps']:>6.2f} Mbps  md5={'OK' if r['md5_ok'] else 'FAIL'}")
if out:
    json.dump(summ, open(out, "w"), indent=1)
    print(f"\nwrote {out}")

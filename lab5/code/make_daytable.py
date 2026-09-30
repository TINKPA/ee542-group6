#!/usr/bin/env python3
"""Per-day table: one row per phone-day, plus the day list the atlas draws.

`path_km` sums only consecutive pairs closer together in time than
GAP_HOLE_S, so a blackout contributes nothing instead of contributing a
straight line between its endpoints.  The unclipped sum over phoneA on
2026-09-27 is 138.6 km, none of which was measured.

    python3 code/make_daytable.py --out report/figures --min-km 2
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from figs_common import load, stops, local_day, haversine, GAP_HOLE_S

DEVICES = ["phoneA", "phoneB", "phoneC"]


def per_day(device):
    rows = load(device)
    st = stops(rows)
    out = {}
    for i, r in enumerate(rows):
        out.setdefault(local_day(r["t"]), {"n": 0, "km": 0.0, "gap": 0,
                                           "vmax": 0.0, "ssid": set(), "stops": 0})
        out[local_day(r["t"])]["n"] += 1
        if r["vel"]:
            out[local_day(r["t"])]["vmax"] = max(out[local_day(r["t"])]["vmax"], r["vel"])
        if r["ssid"]:
            out[local_day(r["t"])]["ssid"].add(r["ssid"])
    for i in range(1, len(rows)):
        gap = rows[i]["t"] - rows[i - 1]["t"]
        d = local_day(rows[i - 1]["t"])
        if gap > GAP_HOLE_S:
            out[d]["gap"] = max(out[d]["gap"], gap)
            continue
        out[d]["km"] += haversine(rows[i - 1]["lat"], rows[i - 1]["lon"],
                                  rows[i]["lat"], rows[i]["lon"]) / 1000.0
    for s in st:
        out.setdefault(local_day(s["start"]), {"n": 0, "km": 0.0, "gap": 0,
                                               "vmax": 0.0, "ssid": set(), "stops": 0})
        out[local_day(s["start"])]["stops"] += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="report/figures")
    ap.add_argument("--min-km", type=float, default=2.0)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    recs = []
    for dev in DEVICES:
        for day, v in sorted(per_day(dev).items()):
            recs.append({"device": dev, "day": day, "fixes": v["n"],
                         "path_km": round(v["km"], 1), "stops": v["stops"],
                         "vmax_kmh": int(v["vmax"]), "ssids": len(v["ssid"]),
                         "max_gap_min": int(v["gap"] / 60)})
    with open(os.path.join(args.out, "daytable.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(recs[0].keys()))
        w.writeheader()
        w.writerows(recs)

    md = ["| device | day | fixes | path km | stops | v max | SSIDs | max gap |",
          "|---|---|---|---|---|---|---|---|"]
    for r in recs:
        g = f"{r['max_gap_min']} min" if r["max_gap_min"] else "--"
        md.append(f"| {r['device']} | {r['day'][5:]} | {r['fixes']} | {r['path_km']} | "
                  f"{r['stops']} | {r['vmax_kmh']} | {r['ssids']} | {g} |")
    with open(os.path.join(args.out, "daytable.md"), "w") as f:
        f.write("\n".join(md) + "\n")

    keep = [r for r in recs if r["path_km"] >= args.min_km]
    with open(os.path.join(args.out, "atlas_days.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["device", "day"])
        w.writeheader()
        w.writerows([{"device": r["device"], "day": r["day"]} for r in keep])
    print("\n".join(md))
    print(f"\n{len(recs)} phone-days, {len(keep)} with path >= {args.min_km} km -> atlas")


if __name__ == "__main__":
    main()

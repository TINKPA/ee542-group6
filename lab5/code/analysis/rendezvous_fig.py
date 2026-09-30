#!/usr/bin/env python3
"""Pairwise separation over time, and the encounters that survive the test.

Two tracks never share a timestamp -- each phone reports on its own trigger --
so both are resampled onto one 30 s grid by carrying the last fix forward, but
only while it is fresher than MAX_AGE_S.  Past that the phone is position
unknown, not still there; without the cut a handset that stops reporting keeps
standing next to whoever it was last near.

Together means the claim survives both accuracy figures:

    haversine(a, b) - acc_a - acc_b <= RADIUS_M

    uv run --with matplotlib --with numpy python code/analysis/rendezvous_fig.py
"""
import itertools
import json
import os
import sys
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import LAB5, haversine, load

FIGS = os.path.join(LAB5, "report", "figures")
PHONES = ["phoneA", "phoneB", "phoneC"]
GRID_S = 30
MAX_AGE_S = 180
RADIUS_M = 25.0
MIN_RUN_S = 60
PAIR_COLOR = {("phoneA", "phoneB"): "#d62728", ("phoneA", "phoneC"): "#2ca02c"}


def resample(rows, t0, t1):
    out, i, t = {}, 0, t0
    while t <= t1:
        while i + 1 < len(rows) and rows[i + 1]["ts"] <= t:
            i += 1
        if rows[i]["ts"] <= t and t - rows[i]["ts"] <= MAX_AGE_S:
            out[t] = rows[i]
        t += GRID_S
    return out


def main():
    os.makedirs(FIGS, exist_ok=True)
    P = {p: load(p) for p in PHONES}
    series, encounters, stats = {}, {}, {}
    for a, b in itertools.combinations(PHONES, 2):
        t0 = max(P[a][0]["ts"], P[b][0]["ts"])
        t1 = min(P[a][-1]["ts"], P[b][-1]["ts"])
        if t1 <= t0:
            continue
        ga, gb = resample(P[a], t0, t1), resample(P[b], t0, t1)
        common = sorted(set(ga) & set(gb))
        pts, hits = [], []
        for t in common:
            d = haversine(ga[t]["lat"], ga[t]["lon"], gb[t]["lat"], gb[t]["lon"])
            acc = (ga[t]["acc"] or 0) + (gb[t]["acc"] or 0)
            pts.append((t, d))
            if d - acc <= RADIUS_M:
                hits.append((t, d))
        series[(a, b)] = pts
        runs, cur = [], None
        for t, d in hits:
            if cur and t - cur[1] <= 2 * GRID_S:
                cur[1] = t
                cur[3] = min(cur[3], d)
            else:
                if cur and cur[1] - cur[0] >= MIN_RUN_S:
                    runs.append(cur)
                cur = [t, t, 0, d]
        if cur and cur[1] - cur[0] >= MIN_RUN_S:
            runs.append(cur)
        encounters[(a, b)] = runs
        stats[f"{a}-{b}"] = {
            "overlap_h": (t1 - t0) / 3600.0, "cells": len(common),
            "min_sep_m": min((d for _, d in pts), default=None),
            "encounters": len(runs),
            "total_min": sum((r[1] - r[0]) for r in runs) / 60.0,
        }

    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    for pair, pts in series.items():
        if not pts:
            continue
        xs = [datetime.fromtimestamp(t) for t, _ in pts]
        ys = [max(d, 0.5) for _, d in pts]
        ax.plot(xs, ys, lw=0.9, alpha=0.85, color=PAIR_COLOR.get(pair, "#777777"),
                label=f"{pair[0]}–{pair[1]}")
        for r in encounters[pair]:
            ax.axvspan(datetime.fromtimestamp(r[0]), datetime.fromtimestamp(r[1]),
                       color=PAIR_COLOR.get(pair, "#777777"), alpha=0.22, lw=0)
    ax.axhline(RADIUS_M, color="black", ls="--", lw=1.3,
               label=f"threshold {RADIUS_M:.0f} m")
    ax.set_yscale("log")
    ax.set_ylabel("separation (m)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.legend(fontsize=8, loc="lower left", framealpha=0.95, ncol=3)
    ax.grid(alpha=0.25, which="both")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "fig_rendezvous.pdf"))
    plt.close(fig)

    for k, v in stats.items():
        print(f"{k}: overlap {v['overlap_h']:.1f} h, cells {v['cells']}, "
              f"min {v['min_sep_m']:.0f} m, encounters {v['encounters']}, "
              f"{v['total_min']:.0f} min together")
    out = os.path.join(LAB5, "report", "results.json")
    prev = json.load(open(out)) if os.path.exists(out) else {}
    prev.update({"rendezvous": {"radius_m": RADIUS_M, "grid_s": GRID_S,
                                "max_age_s": MAX_AGE_S, "pairs": stats}})
    json.dump(prev, open(out, "w"), indent=2)
    print(f"figure -> {FIGS}/fig_rendezvous.pdf")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Day strip: every phone-day as two stacked bands on one 24 h axis.

Upper band is what the phone was doing (at its most-used place, at some other
stop, or moving); lower band is the interval between consecutive fixes.
Stacking them on one axis is the point: the stretches where the lower band goes
dense are the stretches where the upper band says "moving".

A gap longer than GAP_HOLE_S is drawn as nothing at all.  Filling it would
present missing data as a state the phone was in, which is the same mistake the
hub's own trip map makes when it draws a straight line across a 16 h blackout.

    python3 code/make_daystrip.py --out report/figures
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.patches import Patch
import matplotlib.cm as cm

from figs_common import (load, stops, place_ids, local_day, seconds_into_day,
                         GAP_HOLE_S)

DEVICES = ["phoneA", "phoneB", "phoneC"]
C_BASE = "#1f6feb"
C_STOP = "#f0883e"
C_MOVE = "#8b949e"
CMAP = plt.get_cmap("viridis_r")


def build(device):
    rows = load(device)
    st = stops(rows)
    ids, _ = place_ids(st)
    # fix index -> place id
    place = [None] * len(rows)
    dur = {}
    for s, pid in zip(st, ids):
        for k in range(s["i0"], s["i1"] + 1):
            place[k] = pid
        dur[pid] = dur.get(pid, 0) + s["dur"]
    base = max(dur, key=dur.get) if dur else None
    days = {}
    for i in range(1, len(rows)):
        gap = rows[i]["t"] - rows[i - 1]["t"]
        if gap <= 0 or gap > GAP_HOLE_S:
            continue
        d = local_day(rows[i - 1]["t"])
        x0 = seconds_into_day(rows[i - 1]["t"]) / 3600.0
        x1 = x0 + gap / 3600.0
        if x1 > 24:
            x1 = 24.0
        p = place[i - 1]
        c = C_MOVE if p is None else (C_BASE if p == base else C_STOP)
        days.setdefault(d, []).append((x0, x1 - x0, c, gap))
    return days


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="report/figures")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    data = {d: build(d) for d in DEVICES}
    rowlist = [(d, day) for d in DEVICES for day in sorted(data[d])]
    n = len(rowlist)

    fig, ax = plt.subplots(figsize=(11, 0.62 * n + 1.5))
    norm = LogNorm(vmin=1, vmax=GAP_HOLE_S)
    H = 0.30
    yt, yl = [], []
    for k, (dev, day) in enumerate(rowlist):
        y = n - k
        for x0, w, c, gap in data[dev][day]:
            ax.barh(y + 0.17, w, left=x0, height=H, color=c, linewidth=0)
            ax.barh(y - 0.17, w, left=x0, height=H,
                    color=CMAP(norm(max(gap, 1))), linewidth=0)
        yt.append(y)
        yl.append(f"{dev[-1]}  {day[5:]}")
    prev = None
    for k, (dev, _) in enumerate(rowlist):
        if prev is not None and dev != prev:
            ax.axhline(n - k + 0.5, color="#30363d", lw=0.8)
        prev = dev

    ax.set_yticks(yt)
    ax.set_yticklabels(yl, fontsize=8, family="monospace")
    ax.set_xlim(0, 24)
    ax.set_ylim(0.3, n + 0.8)
    ax.set_xticks(range(0, 25, 3))
    ax.set_xticklabels([f"{h:02d}" for h in range(0, 25, 3)], fontsize=8)
    ax.set_xlabel("hour of day (PDT)", fontsize=9)
    ax.grid(axis="x", color="#d0d7de", lw=0.5, alpha=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)

    ax.legend(handles=[Patch(color=C_BASE, label="most-used place"),
                       Patch(color=C_STOP, label="other stop"),
                       Patch(color=C_MOVE, label="moving"),
                       Patch(facecolor="white", edgecolor="#d0d7de", label="no data")],
              loc="upper center", bbox_to_anchor=(0.5, -0.055),
              ncol=4, frameon=False, fontsize=8)
    cb = fig.colorbar(cm.ScalarMappable(norm=norm, cmap=CMAP), ax=ax,
                      pad=0.015, fraction=0.025)
    cb.set_label("interval between fixes (s)", fontsize=8)
    cb.ax.tick_params(labelsize=7)

    fig.tight_layout()
    for ext in ("png", "pdf"):
        p = os.path.join(args.out, f"daystrip.{ext}")
        fig.savefig(p, dpi=200, bbox_inches="tight")
        print("wrote", p)


if __name__ == "__main__":
    main()

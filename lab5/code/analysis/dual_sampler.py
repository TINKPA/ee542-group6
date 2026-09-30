#!/usr/bin/env python3
"""Two samplers on one handset: distance-triggered against time-triggered.

The same iPhone that publishes to the hub as phoneA also runs the Home
Assistant companion app, which reports to a recorder on the LAN.  Same device,
same GPS, same trips, same hours -- only the publishing policy differs.  Each
fix pair gives a (gap, step): OwnTracks holds the step and lets the gap float,
HA holds the gap and lets the step float, so on a log-log plot one lies along a
horizontal band and the other along a vertical one.

Restricted to the window both recorders were active, and to pairs under
MAX_VALID_GAP_S on the OwnTracks side / 15 min on the HA side, so a suspended
app does not enter as a sampling decision.

    uv run --with matplotlib --with numpy python code/analysis/dual_sampler.py
"""
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import LAB5, MAX_VALID_GAP_S, displacement_m, haversine, load, median

FIGS = os.path.join(LAB5, "report", "figures")
HA_PATH = os.path.join(LAB5, "data", "ha_daniels_iphone.jsonl")
HA_MAX_GAP_S = 900.0
C_OT = "#1f77b4"
C_HA = "#e65100"


def ha_pairs():
    rows = []
    with open(HA_PATH) as f:
        for line in f:
            r = json.loads(line)
            rows.append((r["tst"], r["lat"], r["lon"]))
    rows.sort()
    out = []
    for a, b in zip(rows, rows[1:]):
        gap = b[0] - a[0]
        if gap <= 0 or gap > HA_MAX_GAP_S:
            continue
        out.append((gap, haversine(a[1], a[2], b[1], b[2])))
    return rows, out


def ot_pairs(t0, t1):
    fixes = [f for f in load("phoneA") if t0 <= f["ts"] <= t1]
    out = []
    for a, b in zip(fixes, fixes[1:]):
        gap = b["ts"] - a["ts"]
        if gap <= 0 or gap > MAX_VALID_GAP_S:
            continue
        out.append((gap, haversine(a["lat"], a["lon"], b["lat"], b["lon"])))
    return out


def cv(xs):
    m = sum(xs) / len(xs)
    sd = (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5
    return sd / m if m else float("nan")


def main():
    os.makedirs(FIGS, exist_ok=True)
    ha_rows, ha = ha_pairs()
    t0, t1 = ha_rows[0][0], ha_rows[-1][0]
    ot = ot_pairs(t0, t1)
    # only pairs where the phone actually moved: a parked phone makes both
    # samplers look identical and would bury the contrast in a corner.
    ha_m = [(g, s) for g, s in ha if s >= 25]
    ot_m = [(g, s) for g, s in ot if s >= 25]

    fig, ax = plt.subplots(figsize=(6.6, 4.2))
    for pairs, c, lab in ((ot_m, C_OT, "OwnTracks"), (ha_m, C_HA, "Home Assistant")):
        g = [p[0] for p in pairs]
        s = [p[1] for p in pairs]
        ax.scatter(g, s, s=9, alpha=0.30, color=c, linewidths=0,
                   label=f"{lab}  (n={len(pairs)}, "
                         f"CV$_{{gap}}$={cv(g):.2f}, CV$_{{step}}$={cv(s):.2f})")
        ax.axhline(median(s), color=c, ls="--", lw=1.2)
        ax.axvline(median(g), color=c, ls=":", lw=1.2)
    ax.axhline(displacement_m("phoneA"), color="black", ls="--", lw=1.3,
               label="D = 50 m")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("inter-fix gap (s)")
    ax.set_ylabel("step between fixes (m)")
    ax.legend(fontsize=7.5, loc="upper left", framealpha=0.95)
    ax.grid(alpha=0.25, which="both")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "fig_dual_sampler.pdf"))
    plt.close(fig)

    res = {"dual_sampler": {}}
    for name, pairs in (("owntracks", ot_m), ("home_assistant", ha_m)):
        g = [p[0] for p in pairs]; s = [p[1] for p in pairs]
        res["dual_sampler"][name] = {
            "n": len(pairs), "median_gap_s": median(g), "median_step_m": median(s),
            "cv_gap": cv(g), "cv_step": cv(s)}
        print(f"{name:16s} n={len(pairs):5d}  gap med {median(g):6.0f}s CV {cv(g):.2f}   "
              f"step med {median(s):7.0f}m CV {cv(s):.2f}")
    out = os.path.join(LAB5, "report", "results.json")
    prev = json.load(open(out)) if os.path.exists(out) else {}
    prev.update(res)
    json.dump(prev, open(out, "w"), indent=2)
    print(f"figure -> {FIGS}/fig_dual_sampler.pdf")


if __name__ == "__main__":
    main()

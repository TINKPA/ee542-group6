#!/usr/bin/env python3
"""The sampling law: gap = min(locatorInterval, locatorDisplacement / v).

Produces the two figures the argument rests on and the band table, for both
handsets independently.  Run:

    uv run --with matplotlib python code/analysis/cadence.py
"""
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (LAB5, LAW_K, LOCATOR_DISPLACEMENT_M, LOCATOR_INTERVAL_S,
                    CROSSOVER_KMH, SETTINGS, crossover_kmh, displacement_m,
                    interval_s, intervals, law_gap, load, median)

PHONES = ["phoneA", "phoneB", "phoneC"]
# phoneC is drawn in a third colour because it is a different experiment,
# not a third replicate: its locatorDisplacement is 200 m.
COLORS = {"phoneA": "#1f77b4", "phoneB": "#d62728", "phoneC": "#2ca02c"}
BANDS = [(0, 1), (1, 3), (3, 5), (5, 15), (15, 30), (30, 60), (60, 90), (90, 200)]
FIGS = os.path.join(LAB5, "report", "figures")


def band_table(rows, phone="phoneA"):
    out = []
    for lo, hi in BANDS:
        sel = [r for r in rows if r["vel"] is not None and lo <= r["vel"] < hi]
        if len(sel) < 8:
            continue
        mv = median([r["vel"] for r in sel])
        out.append({
            "lo": lo, "hi": hi, "n": len(sel),
            "median_gap": median([r["gap"] for r in sel]),
            "median_step": median([r["step"] for r in sel]),
            "median_vel": mv,
            "predicted_gap": law_gap(mv, phone),
        })
    return out


def fig_law(data):
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    for p in PHONES:
        rows = [r for r in data[p] if r["vel"] is not None and r["vel"] > 0]
        ax.scatter([r["vel"] for r in rows], [r["gap"] for r in rows],
                   s=4, alpha=0.22, color=COLORS[p], linewidths=0, label=None)
    v = np.logspace(np.log10(0.6), np.log10(160), 400)
    # One curve per distinct D, not one per phone: two of the handsets share a
    # configuration and would draw the same line twice.
    for d, style in ((50.0, "-"), (200.0, "--")):
        ref = next(q for q in PHONES if displacement_m(q) == d)
        ax.plot(v, [law_gap(x, ref) for x in v], color="black", lw=2.0,
                ls=style, zorder=5,
                label=f"min(I, D/v),  I = 60 s,  D = {d:.0f} m")
    for p in PHONES:
        bt = band_table(data[p], p)
        ax.plot([b["median_vel"] for b in bt], [b["median_gap"] for b in bt],
                "o-", color=COLORS[p], ms=5, lw=1.4, zorder=6,
                label=f"{p} (D={displacement_m(p):.0f} m, n={sum(b['n'] for b in bt)})")
    for p, lab in (("phoneA", "walking pace"), ("phoneC", None)):
        ax.axvline(crossover_kmh(p), color="gray", ls="--", lw=1.0, zorder=4)
    ax.text(crossover_kmh("phoneA") * 1.15, 96,
            f"$v^\\star$ {crossover_kmh('phoneA'):.0f}", fontsize=8,
            color="gray", va="top", ha="left")
    ax.text(crossover_kmh("phoneC") * 1.15, 96,
            f"$v^\\star$ {crossover_kmh('phoneC'):.0f}", fontsize=8,
            color="gray", va="top", ha="left")
    ax.text(0.72, 21, "interval-governed", fontsize=8.5, color="0.25")
    ax.text(30, 21, "displacement-governed", fontsize=8.5, color="0.25")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(0.6, 160); ax.set_ylim(1.2, 110)
    ax.set_xlabel("reported speed $v$ (km/h)")
    ax.set_ylabel("inter-fix gap (s)")
    ax.legend(fontsize=7.5, loc="lower left", framealpha=0.95, handlelength=1.8)
    ax.grid(alpha=0.25, which="both")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "fig_law.pdf"))
    plt.close(fig)


def fig_step(data):
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    for p in PHONES:
        bt = band_table(data[p], p)
        ax.plot([b["median_vel"] for b in bt], [b["median_step"] for b in bt],
                "o-", color=COLORS[p], ms=5, lw=1.4,
                label=f"{p} (D={displacement_m(p):.0f} m)")
    for d, style in ((50.0, "--"), (200.0, ":")):
        ax.axhline(d, color="black", ls=style, lw=1.4,
                   label=f"D = {d:.0f} m  (locatorDisplacement)")
    for p in ("phoneA", "phoneC"):
        ax.axvline(crossover_kmh(p), color="gray", ls="--", lw=1.0)
    ax.set_xscale("log")
    ax.set_xlim(0.6, 160); ax.set_ylim(0, 230)
    ax.set_xlabel("reported speed $v$ (km/h)")
    ax.set_ylabel("median step (m)")
    ax.legend(fontsize=8, loc="lower right")
    ax.grid(alpha=0.25, which="both")
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "fig_step.pdf"))
    plt.close(fig)


def battery_regimes(phone):
    """Drain while unplugged, split by whether the phone was moving."""
    fixes = load(phone)
    segs = {"stationary": [], "moving": []}
    for a, b in zip(fixes, fixes[1:]):
        dt = b["ts"] - a["ts"]
        if not (0 < dt <= 300) or a["bs"] != "1" or b["bs"] != "1":
            continue
        if a["batt"] is None or b["batt"] is None:
            continue
        key = "moving" if (b["vel"] or 0) >= 3 else "stationary"
        segs[key].append((dt, a["batt"] - b["batt"]))
    out = {}
    for k, v in segs.items():
        if not v:
            continue
        hours = sum(d for d, _ in v) / 3600.0
        drop = sum(p for _, p in v)
        out[k] = {"hours": hours, "points": drop,
                  "rate_pph": drop / hours if hours else float("nan")}
    return out


def main():
    os.makedirs(FIGS, exist_ok=True)
    data = {p: intervals(load(p)) for p in PHONES}
    res = {"constants": {"settings": SETTINGS,
                         "crossover_kmh": {q: crossover_kmh(q) for q in PHONES}},
           "phones": {}}
    for p in PHONES:
        fixes = load(p)
        bt = band_table(data[p], p)
        span_h = (fixes[-1]["ts"] - fixes[0]["ts"]) / 3600.0
        res["phones"][p] = {
            "fixes": len(fixes), "intervals": len(data[p]), "span_h": span_h,
            "bands": bt,
            "battery": battery_regimes(p),
        }
        print(f"\n=== {p}: {len(fixes)} fixes over {span_h:.1f} h ===")
        print(f"{'v (km/h)':<10}{'n':>6}{'med gap':>9}{'pred':>8}{'ratio':>8}{'med step':>10}")
        for b in bt:
            print(f"{f'{b['lo']}-{b['hi']}':<10}{b['n']:>6}{b['median_gap']:>8.0f}s"
                  f"{b['predicted_gap']:>7.0f}s{b['median_gap']/b['predicted_gap']:>8.2f}"
                  f"{b['median_step']:>9.0f}m")
        for k, v in res["phones"][p]["battery"].items():
            print(f"  battery {k:<11}: {v['rate_pph']:.1f} %/h over {v['hours']:.1f} h unplugged")
    fig_law(data); fig_step(data)
    out = os.path.join(LAB5, "report", "results.json")
    prev = json.load(open(out)) if os.path.exists(out) else {}
    prev.update(res)
    json.dump(prev, open(out, "w"), indent=2)
    print(f"\nfigures -> {FIGS}\nresults -> {out}")


if __name__ == "__main__":
    main()

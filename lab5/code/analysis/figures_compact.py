#!/usr/bin/env python3
"""Two multi-panel figures for the short version of the report.

The full report gives the law, the step, the day and the map a float each.
At three pages that is more float overhead than the content needs, so the
pairs that make one point together are drawn as one figure with two panels.
The single-panel versions stay in cadence.py and segment.py because the long
version of the report still uses them.

    uv run --with matplotlib --with numpy python code/analysis/figures_compact.py
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cadence import COLORS, PHONES, band_table
from common import (LAB5, CROSSOVER_KMH, LOCATOR_DISPLACEMENT_M, crossover_kmh,
                    displacement_m,
                    LOCATOR_INTERVAL_S, intervals, law_gap, load)
from estimator import VALID_MIN_KMH, estimate
from segment import CLASS_COLOR, busiest_day, classify_timing, runs

FIGS = os.path.join(LAB5, "report", "figures")


def panel_law(ax, data):
    for p in PHONES:
        rows = [r for r in data[p] if r["vel"] is not None and r["vel"] > 0]
        ax.scatter([r["vel"] for r in rows], [r["gap"] for r in rows],
                   s=3, alpha=0.18, color=COLORS[p], linewidths=0)
    v = np.logspace(np.log10(0.6), np.log10(160), 400)
    ax.plot(v, [law_gap(x) for x in v], color="black", lw=1.8, zorder=5,
            label="min(I, D/v)")
    for p in PHONES:
        bt = band_table(data[p], p)
        ax.plot([b["median_vel"] for b in bt], [b["median_gap"] for b in bt],
                "o-", color=COLORS[p], ms=4, lw=1.2, zorder=6, label=p)
    for q in ("phoneA", "phoneC"):
        ax.axvline(crossover_kmh(q), color="gray", ls="--", lw=1.0)
    ax.text(crossover_kmh("phoneA") * 1.2, 80, "$v^\\star$", fontsize=9, color="gray")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(0.6, 160); ax.set_ylim(1.2, 110)
    ax.set_xlabel("speed $v$ (km/h)"); ax.set_ylabel("inter-fix gap (s)")
    ax.legend(fontsize=7, loc="lower left", framealpha=0.95)
    ax.grid(alpha=0.25, which="both")


def panel_step(ax, data):
    for p in PHONES:
        bt = band_table(data[p], p)
        ax.plot([b["median_vel"] for b in bt], [b["median_step"] for b in bt],
                "o-", color=COLORS[p], ms=4, lw=1.2, label=p)
    for d, style in ((50.0, "--"), (200.0, ":")):
        ax.axhline(d, color="black", ls=style, lw=1.3, label=f"D = {d:.0f} m")
    for q in ("phoneA", "phoneC"):
        ax.axvline(crossover_kmh(q), color="gray", ls="--", lw=1.0)
    ax.set_xscale("log")
    ax.set_xlim(0.6, 160); ax.set_ylim(0, 70)
    ax.set_xlabel("speed $v$ (km/h)"); ax.set_ylabel("median step (m)")
    ax.legend(fontsize=7, loc="lower right")
    ax.grid(alpha=0.25, which="both")


def panel_scatter(ax, data):
    for p in PHONES:
        pairs = estimate(data[p], d_eff=displacement_m(p))
        xs = [r["vel"] for r, vh in pairs
              if vh is not None and r["vel"] and r["vel"] >= VALID_MIN_KMH]
        ys = [vh for r, vh in pairs
              if vh is not None and r["vel"] and r["vel"] >= VALID_MIN_KMH]
        ax.scatter(xs, ys, s=3, alpha=0.14, color=COLORS[p], linewidths=0)
    lim = [VALID_MIN_KMH, 160]
    ax.plot(lim, lim, "k--", lw=1.1, label="$\\hat v = v$")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(*lim); ax.set_ylim(*lim)
    ax.set_xlabel("reported speed $v$ (km/h)", fontsize=8)
    ax.set_ylabel("$\\hat v$ from timing (km/h)", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.legend(fontsize=7, loc="upper left"); ax.grid(alpha=0.25, which="both")


def panel_smooth(ax, res):
    for p in PHONES:
        ks = res["estimator"]["smoothing_k"][p]
        ax.plot([e["k"] for e in ks], [100 * e["median_rel_err"] for e in ks],
                "o-", ms=4, color=COLORS[p], label=p)
        ax.axhline(100 * res["estimator"]["oracle"][p]["coord_median_rel_err"],
                   color=COLORS[p], ls=":", lw=1.1)
    ax.set_xlabel("gaps averaged, $k$", fontsize=8)
    ax.set_ylabel("median rel. error (%)", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.legend(fontsize=7); ax.grid(alpha=0.25)


def panel_map(ax, data):
    for p in PHONES:
        rows = data[p]
        for cls in ("walk", "drive"):
            xs, ys, ok = [], [], False
            for r in rows:
                if classify_timing(r, p) != cls:
                    if ok:
                        xs.append(float("nan")); ys.append(float("nan"))
                    ok = False
                    continue
                xs.append(r["lon"]); ys.append(r["lat"]); ok = True
            ax.plot(xs, ys, color=CLASS_COLOR[cls],
                    lw=1.3 if cls == "walk" else 0.6, alpha=0.9,
                    zorder=3 if cls == "walk" else 2)
        st = [x for x in runs(rows, p) if x["cls"] == "stop"
              and (x["t1"] - x["t0"]) >= 600]
        ax.scatter([x["lon"] for x in st], [x["lat"] for x in st],
                   s=[3 + 40 * ((x["t1"] - x["t0"]) / 3600.0) ** 0.5 for x in st],
                   color=CLASS_COLOR["stop"], alpha=0.45, linewidths=0.4,
                   edgecolors="white", zorder=4)
    ax.set_aspect(1 / 0.827)
    ax.set_xlabel("longitude", fontsize=8); ax.set_ylabel("latitude", fontsize=8)
    ax.tick_params(labelsize=6)
    ax.grid(alpha=0.2)


def panel_day(ax, data):
    p = max(PHONES, key=lambda q: sum(1 for r in data[q]
                                      if classify_timing(r, q) != "stop"))
    day, t0, t1 = busiest_day(data[p], p)
    for seg in runs([r for r in data[p] if t0 <= r["t"] <= t1], p):
        ax.axvspan(max(0.0, (seg["t0"] - t0) / 3600.0),
                   min(24.0, (seg["t1"] - t0) / 3600.0),
                   color=CLASS_COLOR[seg["cls"]], lw=0)
    ax.set_yticks([])
    ax.set_xlim(0, 24); ax.set_xticks(range(0, 25, 3))
    ax.set_xticklabels([f"{h:02d}" for h in range(0, 25, 3)], fontsize=7)
    ax.set_xlabel(f"hour of day, {p} {day[5:]} (PDT)", fontsize=8)
    h = [plt.Line2D([0], [0], color=c, lw=5) for c in CLASS_COLOR.values()]
    ax.legend(h, list(CLASS_COLOR), ncol=3, fontsize=7,
              loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False)


def main():
    import json
    data = {p: intervals(load(p)) for p in PHONES}
    res = json.load(open(os.path.join(LAB5, "report", "results.json")))

    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.45))
    panel_law(axes[0], data); panel_step(axes[1], data)
    fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig_law_step.pdf")); plt.close(fig)

    fig = plt.figure(figsize=(7.2, 3.1))
    gs = fig.add_gridspec(2, 3, height_ratios=[3.0, 0.55], hspace=1.05, wspace=0.38)
    panel_scatter(fig.add_subplot(gs[0, 0]), data)
    panel_smooth(fig.add_subplot(gs[0, 1]), res)
    panel_map(fig.add_subplot(gs[0, 2]), data)
    panel_day(fig.add_subplot(gs[1, :]), data)
    fig.savefig(os.path.join(FIGS, "fig_results.pdf"), bbox_inches="tight")
    plt.close(fig)
    print("wrote fig_law_step.pdf, fig_results.pdf ->", FIGS)


if __name__ == "__main__":
    main()

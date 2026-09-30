#!/usr/bin/env python3
"""Additional standalone figures, one fact each, drawn full width.

The short report is figure-driven: each of these carries something the prose
would otherwise have to assert, so it can stay short.  Nothing here is a panel
of something else; every figure stands alone.

    uv run --with matplotlib --with numpy python code/analysis/extra_figs.py
"""
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cadence import COLORS, PHONES, band_table
from common import (LAB5, CROSSOVER_KMH, LOCATOR_DISPLACEMENT_M,
                    LOCATOR_INTERVAL_S, crossover_kmh, displacement_m,
                    interval_s, intervals, load, median)
from estimator import VALID_MIN_KMH, estimate
from segment import CLASS_COLOR, classify_timing, classify_truth

FIGS = os.path.join(LAB5, "report", "figures")


def fig_gap_hist(data):
    """The two regimes as a distribution: a spike at I, a tail below it."""
    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    bins = np.logspace(np.log10(1), np.log10(300), 70)
    for p in PHONES:
        ax.hist([r["gap"] for r in data[p]], bins=bins, histtype="step",
                lw=1.8, color=COLORS[p], label=f"{p}  (n={len(data[p]):,})")
    ax.axvline(LOCATOR_INTERVAL_S, color="black", ls="--", lw=1.4)
    ax.set_xscale("log")
    # log y: the timer spike is 20x the displacement tail, and on a linear
    # axis it flattens the tail into the baseline, which is the half of the
    # distribution the figure exists to show.
    ax.set_yscale("log")
    ax.set_ylim(1, 2e4)
    ax.text(LOCATOR_INTERVAL_S * 1.15, 6e3, "$I = 60$ s\n(timer fired)", fontsize=10)
    ax.text(3.0, 2e3, "displacement fired", fontsize=10, color="0.3", ha="center")
    ax.annotate("", xy=(1.1, 1.1e3), xytext=(40, 1.1e3),
                arrowprops=dict(arrowstyle="<->", color="0.5", lw=1.0))
    ax.set_xlabel("inter-fix gap (s)", fontsize=11)
    ax.set_ylabel("intervals", fontsize=11)
    ax.legend(fontsize=10); ax.grid(alpha=0.25, which="both")
    fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig_gap_hist.pdf"))
    plt.close(fig)


def fig_rate(data):
    """What the law costs the cloud: reports per hour against speed."""
    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    v = np.logspace(np.log10(0.6), np.log10(160), 300)
    # One bound per distinct D: a larger displacement buys a lower ceiling.
    for d, style in ((50.0, "-"), (200.0, "--")):
        ref = next(q for q in PHONES if displacement_m(q) == d)
        ax.plot(v, [3600 * max(1 / interval_s(ref), x / (3.6 * d)) for x in v],
                color="black", lw=2.0, ls=style,
                label=f"$\\max(1/I,\\ v/D)$, D = {d:.0f} m")
    for p in PHONES:
        bt = band_table(data[p], p)
        ax.plot([b["median_vel"] for b in bt],
                [3600 / b["median_gap"] for b in bt],
                "o-", ms=7, lw=1.6, color=COLORS[p],
                label=f"{p} (D={displacement_m(p):.0f} m)")
    for p in ("phoneA", "phoneC"):
        ax.axvline(crossover_kmh(p), color="gray", ls="--", lw=1.0)
    for y, lab in ((60, "60/h at rest"), (2000, "2,000/h at 100 km/h")):
        ax.axhline(y, color="0.75", lw=0.8, ls=":")
        ax.text(0.65, y * 1.12, lab, fontsize=9, color="0.35")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("speed $v$ (km/h)", fontsize=11)
    ax.set_ylabel("reports per hour", fontsize=11)
    # lower right: the upper left is where the two rate annotations live
    ax.legend(fontsize=10, loc="lower right"); ax.grid(alpha=0.25, which="both")
    fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig_rate.pdf"))
    plt.close(fig)


def fig_err_cdf(data, res):
    """The whole error distribution, not just its median."""
    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    for p in PHONES:
        rows = data[p]
        t_err, c_err = [], []
        for r, vh in estimate(rows):
            if vh is None or r["vel"] is None or r["vel"] < VALID_MIN_KMH:
                continue
            if r["gap"] <= 0 or r["step"] <= 0:
                continue
            t_err.append(abs(vh - r["vel"]) / r["vel"])
            c_err.append(abs(3.6 * r["step"] / r["gap"] - r["vel"]) / r["vel"])
        for errs, ls, lab in ((t_err, "-", "timing only"),
                              (c_err, ":", "coordinates read")):
            x = np.sort(errs)
            ax.plot(100 * x, np.arange(1, len(x) + 1) / len(x), ls,
                    color=COLORS[p], lw=1.8, label=f"{p}, {lab}")
    ax.axhline(0.5, color="0.8", lw=0.8)
    ax.set_xscale("log"); ax.set_xlim(1, 300); ax.set_ylim(0, 1)
    ax.set_xlabel("relative error (%)", fontsize=11)
    ax.set_ylabel("fraction of intervals", fontsize=11)
    ax.legend(fontsize=9, loc="upper left"); ax.grid(alpha=0.25, which="both")
    fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig_err_cdf.pdf"))
    plt.close(fig)


def fig_confusion(data):
    """Where the three-class segmenter is wrong, and it is one class."""
    labels = ["stop", "walk", "drive"]
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.5))
    for ax, p in zip(axes, PHONES):
        m = np.zeros((3, 3))
        for r in data[p]:
            t = classify_truth(r)
            if t is None:
                continue
            m[labels.index(t), labels.index(classify_timing(r))] += 1
        row = m / np.maximum(m.sum(axis=1, keepdims=True), 1)
        ax.imshow(row, cmap="Blues", vmin=0, vmax=1)
        for i in range(3):
            for j in range(3):
                ax.text(j, i, f"{int(m[i, j])}\n{100*row[i, j]:.0f}%",
                        ha="center", va="center", fontsize=9,
                        color="white" if row[i, j] > 0.55 else "black")
        ax.set_xticks(range(3)); ax.set_xticklabels(labels, fontsize=10)
        ax.set_yticks(range(3)); ax.set_yticklabels(labels, fontsize=10)
        ax.set_xlabel("predicted from timing", fontsize=10)
        ax.set_ylabel("from reported speed", fontsize=10)
        acc = np.trace(m) / m.sum()
        ax.set_title(f"{p}   {100*acc:.1f}%   (n={int(m.sum()):,})", fontsize=11)
    fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig_confusion.pdf"))
    plt.close(fig)


def fig_scatter(data):
    """The estimator against ground truth, on its own and full size."""
    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    for p in PHONES:
        pairs = estimate(data[p])
        xs = [r["vel"] for r, vh in pairs
              if vh is not None and r["vel"] and r["vel"] >= VALID_MIN_KMH]
        ys = [vh for r, vh in pairs
              if vh is not None and r["vel"] and r["vel"] >= VALID_MIN_KMH]
        ax.scatter(xs, ys, s=7, alpha=0.20, color=COLORS[p], linewidths=0,
                   label=f"{p}  (n={len(xs):,})")
    lim = [VALID_MIN_KMH, 170]
    ax.plot(lim, lim, "k--", lw=1.4, label="$\\hat v = v$")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(*lim); ax.set_ylim(*lim)
    ax.set_xlabel("reported speed $v$ (km/h)", fontsize=11)
    ax.set_ylabel("$\\hat v$ from arrival times only (km/h)", fontsize=11)
    leg = ax.legend(fontsize=10, loc="upper left")
    for h in leg.legend_handles:
        try:
            h.set_alpha(1.0); h.set_sizes([40])
        except Exception:
            pass
    ax.grid(alpha=0.25, which="both")
    fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig_scatter.pdf"))
    plt.close(fig)


def fig_smooth(res):
    """Averaging gaps makes it worse: the negative result, on its own."""
    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    for p in PHONES:
        ks = res["estimator"]["smoothing_k"][p]
        ax.plot([e["k"] for e in ks], [100 * e["median_rel_err"] for e in ks],
                "o-", ms=8, lw=1.8, color=COLORS[p], label=p)
        y = 100 * res["estimator"]["oracle"][p]["coord_median_rel_err"]
        ax.axhline(y, color=COLORS[p], ls=":", lw=1.4)
    ax.text(5.2, 7.4, "coordinate-reading estimator,\nsame sampling instants",
            fontsize=9, color="0.3")
    ax.set_xlabel("gaps averaged before inverting, $k$", fontsize=11)
    ax.set_ylabel("median relative error (%)", fontsize=11)
    ax.set_ylim(0, 32)
    ax.legend(fontsize=10); ax.grid(alpha=0.25)
    fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig_smooth.pdf"))
    plt.close(fig)


def fig_coverage():
    """When each phone was actually reporting, blackouts included."""
    import time as _t
    fig, ax = plt.subplots(figsize=(7.0, 2.4))
    allfix = {p: load(p) for p in PHONES}
    t0 = min(f[0]["ts"] for f in allfix.values())
    for i, p in enumerate(PHONES):
        fx = allfix[p]
        for a, b in zip(fx, fx[1:]):
            if b["ts"] - a["ts"] <= 300:
                ax.plot([(a["ts"] - t0) / 3600, (b["ts"] - t0) / 3600],
                        [i, i], color=COLORS[p], lw=9, solid_capstyle="butt")
        gaps = [(a["ts"], b["ts"]) for a, b in zip(fx, fx[1:])
                if b["ts"] - a["ts"] > 3600]
        for g0, g1 in gaps:
            ax.text(((g0 + g1) / 2 - t0) / 3600, i + 0.30,
                    f"{(g1-g0)/3600:.1f} h", fontsize=8, ha="center",
                    color="0.35")
    ax.set_yticks(range(len(PHONES))); ax.set_yticklabels(PHONES, fontsize=10)
    ax.set_ylim(-0.6, len(PHONES) - 0.3)
    ax.set_xlabel(f"hours since {_t.strftime('%m-%d %H:%M', _t.localtime(t0))} PDT",
                  fontsize=11)
    ax.grid(alpha=0.25, axis="x")
    fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig_coverage.pdf"))
    plt.close(fig)


def main():
    data = {p: intervals(load(p)) for p in PHONES}
    res = json.load(open(os.path.join(LAB5, "report", "results.json")))
    fig_gap_hist(data); fig_rate(data); fig_err_cdf(data, res)
    fig_confusion(data); fig_coverage()
    fig_scatter(data); fig_smooth(res)
    print("wrote 7 figures ->", FIGS)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Speed from arrival timing alone -- the Lab 5 §6 mapping program.

Above the crossover the publisher is displacement-triggered, so the gap between
two consecutive fixes already encodes how fast the handset was moving:

    v_hat = D / gap          (D = locatorDisplacement)

No coordinates are read.  The estimator consumes only the instants at which
packets arrived at the hub, which is the one channel a gateway sees even when
the payload is opaque to it.  Reported `vel` is used solely as ground truth.

    uv run --with matplotlib --with numpy python code/analysis/estimator.py
"""
import json
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (LAB5, LAW_K, LOCATOR_DISPLACEMENT_M, LOCATOR_INTERVAL_S,
                    CROSSOVER_KMH, crossover_kmh, displacement_m,
                    interval_s, intervals, load, median)

# phoneC carries a 200 m displacement, so its v_hat = D/gap divides by a
# different D.  Passing the phone rather than the constant is what keeps
# the estimator honest across configurations.
PHONES = ["phoneA", "phoneB", "phoneC"]
COLORS = {"phoneA": "#1f77b4", "phoneB": "#d62728", "phoneC": "#2ca02c"}
FIGS = os.path.join(LAB5, "report", "figures")
# Below this the reported speed is quantised too coarsely to grade against:
# `vel` is an integer km/h, so at 4 km/h one count is 25%.
VALID_MIN_KMH = 5.0


def estimate(rows, k=1, d_eff=LOCATOR_DISPLACEMENT_M):
    """v_hat from timing only.  k>1 averages the k most recent gaps."""
    out = []
    gaps = []
    for r in rows:
        gaps.append(r["gap"])
        if len(gaps) > k:
            gaps.pop(0)
        if r["gap"] >= LOCATOR_INTERVAL_S - 1:
            out.append((r, None))          # censored: the timer fired, v <= D/I
            continue
        if len(gaps) < k:
            out.append((r, None))
            continue
        g = sum(gaps) / len(gaps)
        out.append((r, 3.6 * d_eff / g))
    return out


def score(pairs):
    """Relative error against reported vel, on samples where both are defined."""
    errs, n = [], 0
    for r, vh in pairs:
        if vh is None or r["vel"] is None or r["vel"] < VALID_MIN_KMH:
            continue
        errs.append(abs(vh - r["vel"]) / r["vel"])
        n += 1
    if not errs:
        return {"n": 0}
    return {"n": n, "median_rel_err": median(errs),
            "p90_rel_err": sorted(errs)[int(0.9 * len(errs)) - 1],
            "mean_rel_err": sum(errs) / len(errs)}


def oracle_decomposition(rows, d_eff=LOCATOR_DISPLACEMENT_M):
    """Split the timing estimator's error into the two factors that make it.

    Two estimators share the same sampling instants:
        v_coord = 3.6 * step / gap      reads the coordinates
        v_time  = 3.6 * D    / gap      reads only the arrival times
    Their ratio is an identity, not an approximation:
        v_time / v_coord = D / step
    So everything the timing-only estimator gives up relative to one that reads
    positions is the spread of the step distribution about D, and nothing else.
    v_coord is therefore the honest denominator: no estimator restricted to
    these sampling instants and these coordinates does better, and the question
    "what does discarding the coordinates cost" has an exact answer.
    """
    ratios, coord_err = [], []
    for r in rows:
        if r["gap"] >= LOCATOR_INTERVAL_S - 1 or r["step"] <= 0:
            continue
        if r["vel"] is None or r["vel"] < VALID_MIN_KMH:
            continue
        ratios.append(d_eff / r["step"])
        coord_err.append(abs(3.6 * r["step"] / r["gap"] - r["vel"]) / r["vel"])
    if not ratios:
        return {}
    rs = sorted(ratios)
    return {"n": len(ratios),
            "median_D_over_step": median(ratios),
            "iqr_D_over_step": [rs[len(rs) // 4], rs[3 * len(rs) // 4]],
            "coord_median_rel_err": median(coord_err)}


def fit_effective_D(rows):
    """Median step above the crossover: the displacement the trigger really uses.

    The publisher fires on the first CoreLocation update that has *exceeded* D,
    so every step overshoots by whatever distance was covered since the previous
    update.  Modelled as D_eff = D + v*tau, tau is that update granularity.
    """
    sel = [r for r in rows if r["vel"] is not None and r["vel"] >= 15]
    if len(sel) < 20:
        return None
    v = np.array([r["vel"] for r in sel]) / 3.6          # m/s
    s = np.array([r["step"] for r in sel])
    # robust-ish: fit on band medians rather than raw points
    bands = [(15, 30), (30, 60), (60, 90), (90, 200)]
    xs, ys = [], []
    for lo, hi in bands:
        b = [r for r in sel if lo <= r["vel"] < hi]
        if len(b) < 10:
            continue
        xs.append(median([r["vel"] for r in b]) / 3.6)
        ys.append(median([r["step"] for r in b]))
    if len(xs) < 3:
        return None
    A = np.vstack([np.array(xs), np.ones(len(xs))]).T
    tau, d0 = np.linalg.lstsq(A, np.array(ys), rcond=None)[0]
    return {"D0_m": float(d0), "tau_s": float(tau),
            "band_v_ms": [float(x) for x in xs], "band_step_m": [float(y) for y in ys]}


def fig_estimator(data, res):
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.2))
    ax = axes[0]
    for p in PHONES:
        pairs = estimate(data[p])
        xs = [r["vel"] for r, vh in pairs if vh is not None and r["vel"] and r["vel"] >= VALID_MIN_KMH]
        ys = [vh for r, vh in pairs if vh is not None and r["vel"] and r["vel"] >= VALID_MIN_KMH]
        ax.scatter(xs, ys, s=4, alpha=0.12, color=COLORS[p], linewidths=0)
    lim = [VALID_MIN_KMH, 160]
    ax.plot(lim, lim, "k--", lw=1.2, label="$\\hat v = v$")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(*lim); ax.set_ylim(*lim)
    ax.set_xlabel("reported speed $v$ (km/h)")
    ax.set_ylabel("$\\hat v$ from timing only (km/h)")
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(alpha=0.25, which="both")

    ax = axes[1]
    ks = res["estimator"]["smoothing_k"]
    for p in PHONES:
        ax.plot([e["k"] for e in ks[p]], [100 * e["median_rel_err"] for e in ks[p]],
                "o-", color=COLORS[p], label=p)
    for p in PHONES:
        ax.axhline(100 * res["estimator"]["oracle"][p]["coord_median_rel_err"],
                   color=COLORS[p], ls=":", lw=1.2)
    ax.set_xlabel("gaps averaged, $k$")
    ax.set_ylabel("median relative error (%)")
    ax.set_title("dotted: same sampling, coordinates read", fontsize=8.5)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "fig_estimator.pdf"))
    plt.close(fig)


def main():
    os.makedirs(FIGS, exist_ok=True)
    data = {p: intervals(load(p)) for p in PHONES}
    res = {"estimator": {"smoothing_k": {}, "oracle": {}, "d_eff": {},
                         "nominal": {}, "refit": {}, "censored": {}}}
    for p in PHONES:
        rows = data[p]
        D = displacement_m(p)
        res["estimator"]["oracle"][p] = oracle_decomposition(rows, d_eff=D)
        res["estimator"]["d_eff"][p] = fit_effective_D(rows)
        res["estimator"]["nominal"][p] = score(estimate(rows, k=1, d_eff=D))
        ks = []
        for k in (1, 2, 3, 5, 9):
            ks.append({"k": k, **score(estimate(rows, k=k, d_eff=D))})
        res["estimator"]["smoothing_k"][p] = ks
        d = res["estimator"]["d_eff"][p]
        if d:
            res["estimator"]["refit"][p] = score(estimate(rows, k=1, d_eff=d["D0_m"]))
        cen = sum(1 for r in rows if r["gap"] >= interval_s(p) - 1)
        res["estimator"]["censored"][p] = {"n": cen, "frac": cen / len(rows)}

        o = res["estimator"]["oracle"][p]
        print(f"\n=== {p} ===")
        print(f"  censored (timer fired, v <= {crossover_kmh(p):.0f} km/h): "
              f"{cen}/{len(rows)} = {100*cen/len(rows):.0f}%")
        print(f"  coordinate-reading estimator: median rel err "
              f"{100*o['coord_median_rel_err']:.1f}%  (the denominator)")
        print(f"  D/step: median {o['median_D_over_step']:.3f}, "
              f"IQR [{o['iqr_D_over_step'][0]:.3f}, {o['iqr_D_over_step'][1]:.3f}]")
        print(f"  k=1, D={D:.0f} m     : median rel err {100*res['estimator']['nominal'][p]['median_rel_err']:.1f}%"
              f"  (n={res['estimator']['nominal'][p]['n']})")
        if d:
            print(f"  fitted D_eff = {d['D0_m']:.1f} m + v*{d['tau_s']:.2f} s")
            print(f"  k=1, D={d['D0_m']:.1f} m : median rel err "
                  f"{100*res['estimator']['refit'][p]['median_rel_err']:.1f}%")
        for e in ks:
            print(f"    k={e['k']:<2} median {100*e['median_rel_err']:.1f}%  p90 {100*e['p90_rel_err']:.0f}%  n={e['n']}")
    fig_estimator(data, res)
    out = os.path.join(LAB5, "report", "results.json")
    prev = json.load(open(out)) if os.path.exists(out) else {}
    prev.update(res)
    json.dump(prev, open(out, "w"), indent=2)
    print(f"\nfigures -> {FIGS}")


if __name__ == "__main__":
    main()

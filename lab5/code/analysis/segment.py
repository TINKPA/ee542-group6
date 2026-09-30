#!/usr/bin/env python3
"""Segment a track into stop / walk / drive from arrival timing alone.

This is the mapping product the estimator feeds.  Every decision is made from
the instants packets arrived; coordinates are used only to draw the result and
to grade it.  Three classes, with thresholds that follow from the law rather
than from tuning:

    gap >= I           the interval fired, so the phone moved under D in I
                       seconds: v <= D/I = 3 km/h.  STOP (or a slow walk).
    D/gap <  V_WALK    displacement fired but slowly.                 WALK
    D/gap >= V_WALK    displacement fired quickly.                    DRIVE

V_WALK = 12 km/h sits in the empty band between human gait and traffic.

    uv run --with matplotlib python code/analysis/segment.py
"""
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (LAB5, LOCATOR_DISPLACEMENT_M, LOCATOR_INTERVAL_S,
                    CROSSOVER_KMH, crossover_kmh, displacement_m,
                    interval_s, intervals, load, median)

# The stop/walk/drive cut follows from each handset's own I and D, so a
# phone with a 200 m displacement gets a 12 km/h stop boundary, not 3.
PHONES = ["phoneA", "phoneB", "phoneC"]
V_WALK = 12.0
CLASS_COLOR = {"stop": "#8c8c8c", "walk": "#2ca02c", "drive": "#d62728"}
FIGS = os.path.join(LAB5, "report", "figures")
OUT = os.path.join(LAB5, "out")


def classify_timing(r, phone="phoneA"):
    if r["gap"] >= interval_s(phone) - 1:
        return "stop"
    return "walk" if 3.6 * displacement_m(phone) / r["gap"] < V_WALK else "drive"


def classify_truth(r, phone="phoneA"):
    """Ground truth uses the same boundary the timing rule is censored at, so
    the two agree on what 'stop' can possibly mean for this configuration."""
    v = r["vel"]
    if v is None:
        return None
    if v <= crossover_kmh(phone):
        return "stop"
    return "walk" if v < V_WALK else "drive"


def confusion(rows, phone="phoneA"):
    labels = ["stop", "walk", "drive"]
    m = {a: {b: 0 for b in labels} for a in labels}
    n = 0
    for r in rows:
        t = classify_truth(r, phone)
        if t is None:
            continue
        m[t][classify_timing(r, phone)] += 1
        n += 1
    acc = sum(m[a][a] for a in labels) / n if n else float("nan")
    return {"matrix": m, "n": n, "accuracy": acc}


def runs(rows, phone="phoneA"):
    """Collapse consecutive same-class intervals into segments."""
    out = []
    for r in rows:
        c = classify_timing(r, phone)
        if out and out[-1]["cls"] == c and r["t"] - out[-1]["t1"] <= 300:
            out[-1]["t1"] = r["t"]
            out[-1]["dist"] += r["step"]
            out[-1]["n"] += 1
        else:
            out.append({"cls": c, "t0": r["t"] - r["gap"], "t1": r["t"],
                        "dist": r["step"], "n": 1,
                        "lat": r["lat"], "lon": r["lon"]})
    return out


def busiest_day(rows, phone="phoneA"):
    """The calendar day holding the most displacement-triggered intervals.

    Averaged over a whole capture a timeline is almost entirely stop, which
    says nothing; one active day shows the structure the segmenter recovers.
    A calendar day rather than a sliding window so the axis is hour-of-day.
    """
    import time as _t
    from collections import defaultdict
    by = defaultdict(list)
    for r in rows:
        by[_t.strftime("%Y-%m-%d", _t.localtime(r["t"]))].append(r)
    # Require most of a day to be covered before calling it representative:
    # the first and last days of a capture are partial, and one phone lost
    # 13 h overnight, which would show as an empty axis rather than as rest.
    cand = {d: v for d, v in by.items()
            if (v[-1]["t"] - v[0]["t"]) >= 18 * 3600}
    pool = cand or by
    day = max(pool, key=lambda d: sum(1 for r in pool[d]
                                      if classify_timing(r, phone) != "stop"))
    t0 = _t.mktime(_t.strptime(day, "%Y-%m-%d"))
    return day, t0, t0 + 86400


def fig_timeline(data):
    """One full day on one handset, segmented from arrival times alone.

    Single panel on purpose: the figure's job is to show what the segmenter
    reconstructs over a day, not to compare the two phones.  phoneB spent most
    of its capture parked, so its day is one grey bar and carries nothing.
    """
    p = max(PHONES, key=lambda q: sum(1 for r in data[q]
                                      if classify_timing(r, q) != "stop"))
    rows = data[p]
    day, t0, t1 = busiest_day(rows, p)
    fig, ax = plt.subplots(figsize=(6.8, 1.5))
    for seg in runs([r for r in rows if t0 <= r["t"] <= t1], p):
        ax.axvspan(max(0.0, (seg["t0"] - t0) / 3600.0),
                   min(24.0, (seg["t1"] - t0) / 3600.0),
                   color=CLASS_COLOR[seg["cls"]], lw=0)
    ax.set_yticks([])
    ax.set_ylabel(f"{p}\n{day[5:]}", fontsize=8)
    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 2))
    ax.set_xticklabels([f"{h:02d}" for h in range(0, 25, 2)], fontsize=8)
    ax.set_xlabel("hour of day (PDT)")
    handles = [plt.Line2D([0], [0], color=c, lw=6) for c in CLASS_COLOR.values()]
    ax.legend(handles, list(CLASS_COLOR), ncol=3, fontsize=8,
              loc="lower center", bbox_to_anchor=(0.5, 1.02), frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "fig_timeline.pdf"))
    plt.close(fig)


def fig_tracks(data):
    """Where the phone went, and where it stayed.

    Travel is drawn as a line coloured by the timing-only class; stops are
    drawn as circles with area proportional to how long the phone sat there,
    because a stop has no extent and would otherwise be invisible.
    """
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    for p in PHONES:
        rows = data[p]
        for cls in ("walk", "drive"):
            xs, ys = [], []
            prev_ok = False
            for r in rows:
                if classify_timing(r, p) != cls:
                    if prev_ok:
                        xs.append(float("nan")); ys.append(float("nan"))
                    prev_ok = False
                    continue
                xs.append(r["lon"]); ys.append(r["lat"]); prev_ok = True
            ax.plot(xs, ys, color=CLASS_COLOR[cls],
                    lw=2.0 if cls == "walk" else 1.0, alpha=0.9,
                    solid_capstyle="round", zorder=3 if cls == "walk" else 2)
        stops = [s for s in runs(rows, p) if s["cls"] == "stop"
                 and (s["t1"] - s["t0"]) >= 600]
        if stops:
            ax.scatter([s["lon"] for s in stops], [s["lat"] for s in stops],
                       s=[6 + 90 * ((s["t1"] - s["t0"]) / 3600.0) ** 0.5 for s in stops],
                       color=CLASS_COLOR["stop"], alpha=0.45, linewidths=0.6,
                       edgecolors="white", zorder=4)
    ax.set_aspect(1 / 0.827)   # cos(34 deg): keep metres square at this latitude
    ax.set_xlabel("longitude"); ax.set_ylabel("latitude")
    handles = [plt.Line2D([0], [0], color=CLASS_COLOR["drive"], lw=2),
               plt.Line2D([0], [0], color=CLASS_COLOR["walk"], lw=2.5),
               plt.Line2D([0], [0], color=CLASS_COLOR["stop"], lw=0, marker="o",
                          ms=8, alpha=0.5)]
    ax.legend(handles, ["drive", "walk", "stop (area $\\propto$ dwell)"],
              fontsize=8, loc="upper right", framealpha=0.95)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, "fig_tracks.pdf"))
    plt.close(fig)


def write_map(data):
    """Leaflet map of both tracks coloured by the timing-only class."""
    feats = []
    for p in PHONES:
        for seg in runs(data[p], p):
            pass
    lines = {p: [] for p in PHONES}
    for p in PHONES:
        cur, curcls = [], None
        for r in data[p]:
            c = classify_timing(r, p)
            if c != curcls and cur:
                lines[p].append((curcls, cur)); cur = []
            curcls = c
            cur.append([r["lat"], r["lon"]])
        if cur:
            lines[p].append((curcls, cur))
    payload = {p: [{"cls": c, "pts": pts} for c, pts in lines[p] if len(pts) > 1]
               for p in PHONES}
    html = """<!doctype html><html><head><meta charset="utf-8">
<title>EE542 Lab 5 - mode inferred from packet timing</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#m{height:100%%;margin:0}#k{position:absolute;z-index:1000;right:12px;top:12px;
background:#fff;padding:10px 12px;font:13px/1.5 system-ui;border-radius:6px;box-shadow:0 1px 6px #0003}
b{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:6px}</style></head>
<body><div id="k"><div><b style="background:#8c8c8c"></b>stop (timer fired, v&le;3 km/h)</div>
<div><b style="background:#2ca02c"></b>walk (&lt;12 km/h)</div>
<div><b style="background:#d62728"></b>drive (&ge;12 km/h)</div>
<div style="margin-top:6px;color:#666">class from packet arrival times only</div></div>
<div id="m"></div><script>
const D=%s, C={stop:"#8c8c8c",walk:"#2ca02c",drive:"#d62728"};
const m=L.map("m");L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
{attribution:"&copy; OpenStreetMap"}).addTo(m);
let b=[];for(const p in D)for(const s of D[p]){
L.polyline(s.pts,{color:C[s.cls],weight:s.cls==="stop"?2:3,opacity:.85}).addTo(m);b=b.concat(s.pts);}
m.fitBounds(b);</script></body></html>""" % json.dumps(payload)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "mode_map.html")
    open(path, "w").write(html)
    return path


def main():
    os.makedirs(FIGS, exist_ok=True)
    data = {p: intervals(load(p)) for p in PHONES}
    res = {"segmentation": {"v_walk_kmh": V_WALK, "phones": {}}}
    for p in PHONES:
        rows = data[p]
        c = confusion(rows, p)
        segs = runs(rows, p)
        by = {}
        for cls in ("stop", "walk", "drive"):
            sel = [s for s in segs if s["cls"] == cls]
            by[cls] = {"segments": len(sel),
                       "hours": sum(s["t1"] - s["t0"] for s in sel) / 3600.0,
                       "km": sum(s["dist"] for s in sel) / 1000.0}
        res["segmentation"]["phones"][p] = {"confusion": c, "by_class": by}
        print(f"\n=== {p} ===  accuracy {100*c['accuracy']:.1f}%  (n={c['n']})")
        print(f"{'truth\\pred':<12}{'stop':>8}{'walk':>8}{'drive':>8}")
        for a in ("stop", "walk", "drive"):
            print(f"{a:<12}" + "".join(f"{c['matrix'][a][b]:>8}" for b in ("stop", "walk", "drive")))
        for cls, v in by.items():
            print(f"  {cls:<6} {v['segments']:>4} segments  {v['hours']:>6.1f} h  {v['km']:>7.1f} km")
    fig_timeline(data); fig_tracks(data)
    path = write_map(data)
    out = os.path.join(LAB5, "report", "results.json")
    prev = json.load(open(out)) if os.path.exists(out) else {}
    prev.update(res)
    json.dump(prev, open(out, "w"), indent=2)
    print(f"\nmap -> {path}\nfigures -> {FIGS}")


if __name__ == "__main__":
    main()

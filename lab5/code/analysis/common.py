#!/usr/bin/env python3
"""Shared loading and geometry for the Lab 5 analyses.

Everything downstream reads the JSONL written by code/export_hub.py, never the
live hub, so a figure can be regenerated after the EC2 instance is gone.
"""
import json
import math
import os

LAB5 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The two Expert Mode rows that between them decide when a fix is published.
# They are per handset: phoneC was configured with a 200 m displacement while
# the other two ran 50 m, which is what turns a fit into a prediction -- the
# law says its crossover should move from 3 km/h to 12 km/h and its step should
# lock at 200 m instead of 50 m.  Anything that divides by D must therefore ask
# which phone it is holding.
SETTINGS = {
    "phoneA": {"interval_s": 60.0, "displacement_m": 50.0},
    "phoneB": {"interval_s": 60.0, "displacement_m": 50.0},
    "phoneC": {"interval_s": 60.0, "displacement_m": 200.0},
}

# Module-level values are the 50 m configuration, kept so that callers which
# predate phoneC keep meaning what they meant.  New code takes the phone.
LOCATOR_INTERVAL_S = SETTINGS["phoneA"]["interval_s"]
LOCATOR_DISPLACEMENT_M = SETTINGS["phoneA"]["displacement_m"]
# gap = min(I, D/v).  With v in km/h, D/v in seconds is 3.6*D/v = 180/v.
LAW_K = 3.6 * LOCATOR_DISPLACEMENT_M          # 180
CROSSOVER_KMH = 3.6 * LOCATOR_DISPLACEMENT_M / LOCATOR_INTERVAL_S   # 3.0


def interval_s(phone):
    return SETTINGS[phone]["interval_s"]


def displacement_m(phone):
    return SETTINGS[phone]["displacement_m"]


def law_k(phone):
    """Seconds per (km/h) in the displacement branch: gap = law_k / v."""
    return 3.6 * displacement_m(phone)


def crossover_kmh(phone):
    """Speed at which the two triggers coincide; below it the timer governs."""
    return 3.6 * displacement_m(phone) / interval_s(phone)

# Gaps longer than this are not the sampler pacing itself: they are the app
# suspended (iOS Low Power Mode below 20% battery did this for 15.9 h on
# phoneA).  Including them would put mass at arbitrarily large gaps that no
# setting predicts.
MAX_VALID_GAP_S = 300.0


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _num(row, key):
    v = row.get(key)
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load(phone):
    """Location fixes only, chronological, each with the fields the analyses use."""
    path = os.path.join(LAB5, "data", f"hub_{phone}.jsonl")
    out = []
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            if r.get("_type") != "location":
                continue
            lat, lon = _num(r, "lat"), _num(r, "lon")
            if lat is None or lon is None:
                continue
            out.append({"ts": r["ts"] / 1000.0, "lat": lat, "lon": lon,
                        "acc": _num(r, "acc"), "vel": _num(r, "vel"),
                        "batt": _num(r, "batt"), "bs": r.get("bs"),
                        "m": r.get("m"), "conn": r.get("conn"),
                        "ssid": r.get("ssid")})
    out.sort(key=lambda r: r["ts"])
    return out


def intervals(fixes, max_gap=MAX_VALID_GAP_S):
    """Consecutive pairs, annotated with gap, step and the reported speed.

    `vel` is taken from the LATER fix: CoreLocation reports the speed of the
    fix it is delivering, and that fix is the one whose arrival the gap timed.
    """
    rows = []
    for a, b in zip(fixes, fixes[1:]):
        gap = b["ts"] - a["ts"]
        if gap <= 0 or gap > max_gap:
            continue
        rows.append({
            "t": b["ts"], "gap": gap,
            "step": haversine(a["lat"], a["lon"], b["lat"], b["lon"]),
            "vel": b["vel"], "acc": b["acc"], "acc_prev": a["acc"],
            "lat": b["lat"], "lon": b["lon"],
        })
    return rows


def law_gap(v_kmh, phone="phoneA"):
    """Predicted gap in seconds at speed v, for that handset's settings."""
    if v_kmh <= 0:
        return interval_s(phone)
    return min(interval_s(phone), law_k(phone) / v_kmh)


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return float("nan")
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])

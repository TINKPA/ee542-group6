#!/usr/bin/env python3
"""Shared loading + stop detection for the Lab 5 figures.

One place for the two things every figure must agree on: which timestamp is
authoritative, and where the stops are.  If the atlas and the day strip cluster
stops differently their colours stop meaning the same thing.
"""
import json
import math
import os
import time

LAB5 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# One canonical export, the same files code/analysis/common.py reads.
DATA = os.path.join(LAB5, "data")
STOP_RADIUS_M = 150.0
STOP_MIN_S = 600
GAP_HOLE_S = 600          # longer than this is missing data, never interpolated


def haversine(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    h = (math.sin(math.radians(c - a) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(d - b) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


def load(device):
    """Fixes sorted by the handset's own clock, de-duplicated on it.

    `tst` is the phone's timestamp; `server_ts` is when the hub received it.
    Cadence is a property of the sampler, so the handset clock is the right
    one -- network delay must not show up as sampling jitter.
    """
    rows = []
    with open(os.path.join(DATA, f"hub_{device}.jsonl")) as f:
        for line in f:
            r = json.loads(line)
            if r.get("_type") != "location" or "lat" not in r or "lon" not in r:
                continue
            try:
                t = int(r.get("tst") or (r["ts"] // 1000))
            except (TypeError, ValueError):
                continue
            rows.append({
                "t": t,
                "lat": float(r["lat"]), "lon": float(r["lon"]),
                "vel": _f(r.get("vel")), "acc": _f(r.get("acc")),
                "batt": _f(r.get("batt")), "bs": r.get("bs"),
                "conn": r.get("conn"), "ssid": r.get("ssid"), "m": r.get("m"),
            })
    rows.sort(key=lambda x: x["t"])
    out, seen = [], set()
    for r in rows:
        if r["t"] in seen:
            continue
        seen.add(r["t"])
        out.append(r)
    return out


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def stops(rows, radius=STOP_RADIUS_M, min_s=STOP_MIN_S):
    """Anchor-and-extend clustering: hold the first fix, absorb everything that
    stays inside `radius` of it, keep the run if it lasted `min_s`."""
    res, i = [], 0
    while i < len(rows):
        j = i
        while (j + 1 < len(rows)
               and haversine(rows[i]["lat"], rows[i]["lon"],
                             rows[j + 1]["lat"], rows[j + 1]["lon"]) <= radius):
            j += 1
        dur = rows[j]["t"] - rows[i]["t"]
        if dur >= min_s:
            n = j - i + 1
            res.append({
                "start": rows[i]["t"], "end": rows[j]["t"], "dur": dur, "n": n,
                "lat": sum(r["lat"] for r in rows[i:j + 1]) / n,
                "lon": sum(r["lon"] for r in rows[i:j + 1]) / n,
                "i0": i, "i1": j,
            })
            i = j + 1
        else:
            i += 1
    return res


def place_ids(stop_list, merge_m=200.0):
    """Give repeat visits to the same spot one id, so a colour means a place."""
    centres, ids = [], []
    for s in stop_list:
        hit = None
        for k, c in enumerate(centres):
            if haversine(s["lat"], s["lon"], c[0], c[1]) <= merge_m:
                hit = k
                break
        if hit is None:
            centres.append((s["lat"], s["lon"]))
            hit = len(centres) - 1
        ids.append(hit)
    return ids, centres


def local_day(t):
    return time.strftime("%Y-%m-%d", time.localtime(t))


def seconds_into_day(t):
    lt = time.localtime(t)
    return lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec


def day_path_km(rows):
    return sum(haversine(rows[i - 1]["lat"], rows[i - 1]["lon"],
                         rows[i]["lat"], rows[i]["lon"])
               for i in range(1, len(rows))) / 1000.0

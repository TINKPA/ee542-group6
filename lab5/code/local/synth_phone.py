#!/usr/bin/env python3
"""Generate SYNTHETIC OwnTracks tracks for the phones we do not have yet.

Why this exists.  §6 requires data from *multiple* phones (errata E-12), and
the capture in data/owntracks_raw.jsonl is one iPhone standing nearly still —
29 fixes spread over 214 m.  Nothing in it can exercise a co-location
detector.  Until the second and third handsets are configured, this script
stands in for them so code/rendezvous.py can be written and tested.

Everything it emits is fabricated.  Each payload carries "synthetic": 1 so the
flag survives into ThingsBoard telemetry and into any figure made from it, and
the devices are labelled SYNTHETIC in the hub.  No number produced here may be
reported as a measurement.

Model: straight-line interpolation between hand-written waypoints, sampled at
the interval the real phone used (60 s, errata E-14), with seeded Gaussian
jitter on position.  vel and cog are derived from consecutive samples; batt,
p, acc, conn follow the ranges observed in the real capture (Appendix A).

    python3 synth_phone.py --out ../../data/synthetic_phones.jsonl
"""
import argparse
import json
import math
import random

# Anchor = where the real phone (phoneA) actually sat, from the 2026-09-21
# capture.  The synthetic phones move in a local metric frame around it.
ANCHOR_LAT, ANCHOR_LON = 34.038, -118.460
T0 = 1790058076          # tst of the first real fix
INTERVAL = 60            # s, the rate the real phone reported at
WIFI_RADIUS_M = 80       # inside this, the phone is put on 'w', outside 'm'

M_PER_DEG_LAT = 111_320.0


def to_latlon(east_m, north_m):
    lat = ANCHOR_LAT + north_m / M_PER_DEG_LAT
    lon = ANCHOR_LON + east_m / (M_PER_DEG_LAT * math.cos(math.radians(ANCHOR_LAT)))
    return lat, lon


# Waypoints: (seconds after T0, east metres, north metres).  Legs are walked at
# whatever speed the two endpoints imply, so keep them near 1.4 m/s.
TRACKS = {
    "phoneB": {
        "tid": "BB", "user": "phoneB", "batt0": 88,
        "waypoints": [
            (0,    -30, 420),   # starts a few blocks north
            (300,  -10,  30),   # walks down to the anchor  -> meets phoneA
            (1200,   5,  15),   # dwells next to phoneA ~15 min
            (1500, 210,  20),   # leaves east
            (2100, 215,  25),   # waits there -> meets phoneC
            (2700, 480, 120),   # leaves north-east
        ],
    },
    "phoneC": {
        "tid": "CC", "user": "phoneC", "batt0": 61,
        "waypoints": [
            (0,    620, -240),  # starts far south-east
            (900,  400, -120),  # walks north-west
            (1980, 220,  20),   # arrives where phoneB is waiting -> meets it
            (2400, 225,  15),   # dwell ~7 min
            (3000, 600, -300),  # leaves the way it came
        ],
    },
}


def interpolate(waypoints, t):
    if t <= waypoints[0][0]:
        return waypoints[0][1], waypoints[0][2]
    if t >= waypoints[-1][0]:
        return waypoints[-1][1], waypoints[-1][2]
    for (t0, e0, n0), (t1, e1, n1) in zip(waypoints, waypoints[1:]):
        if t0 <= t <= t1:
            f = (t - t0) / (t1 - t0)
            return e0 + f * (e1 - e0), n0 + f * (n1 - n0)
    raise AssertionError("unreachable")


def build(name, spec, rng):
    wp = spec["waypoints"]
    out, prev = [], None
    for t in range(0, wp[-1][0] + 1, INTERVAL):
        east, north = interpolate(wp, t)
        east += rng.gauss(0, 3.0)          # GPS jitter, ~ the acc the phone claims
        north += rng.gauss(0, 3.0)
        lat, lon = to_latlon(east, north)
        d = math.hypot(east, north)
        p = {
            "_type": "location",
            "synthetic": 1,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "tst": T0 + t,
            "acc": 14 if rng.random() > 0.05 else 40,
            "alt": round(55 + north / 200.0, 0),
            "vac": rng.randint(3, 13),
            "batt": max(5, spec["batt0"] - t // 300),
            "bs": 1,
            "conn": "w" if d < WIFI_RADIUS_M else "m",
            "m": 2,
            "t": "t",
            "tid": spec["tid"],
            "inregions": [],
            "inrids": [],
        }
        if prev is not None:
            step = math.hypot(east - prev[0], north - prev[1])
            p["vel"] = round(step / INTERVAL * 3.6)          # km/h, as OwnTracks
            p["cog"] = round(math.degrees(
                math.atan2(east - prev[0], north - prev[1])) % 360)
            p["motionactivities"] = ["walking"] if step > 15 else ["stationary"]
        else:
            p["vel"], p["cog"], p["motionactivities"] = 0, 0, ["stationary"]
        p["p"] = round(100.64 - (p["alt"] - 55) * 0.012, 3)  # barometer vs altitude
        if p["conn"] == "w":
            p["ssid"], p["bssid"] = "TTCC-AX", "f0:2f:74:7e:0b:18"
        out.append({"device": name, "user": spec["user"], "payload": p})
        prev = (east, north)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/synthetic_phones.jsonl")
    ap.add_argument("--seed", type=int, default=542)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    rows = []
    for name, spec in TRACKS.items():
        rows.extend(build(name, spec, rng))
    rows.sort(key=lambda r: r["payload"]["tst"])
    with open(args.out, "w") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    per = {}
    for r in rows:
        per[r["device"]] = per.get(r["device"], 0) + 1
    print(f"wrote {len(rows)} synthetic payloads to {args.out}: " +
          ", ".join(f"{k} {v}" for k, v in sorted(per.items())))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""EE542 Lab 5 — field census over captured OwnTracks payloads.

Reads the sink's JSONL and reports, per message _type, every field the handset
actually emitted: how often, its observed range, and a sample.  The point is to
separate three things the official schema conflates:

  * fields the protocol defines          (owntracks.org/booklet/tech/json)
  * fields THIS phone actually sends     (observed here)
  * fields that carry usable signal      (observed AND varying)

A field that never changes is not data, it is a constant, so `vary` is the
column that decides what is worth building on.

  uv run assignments/lab5/code/census.py [--jsonl PATH] [--type location]
"""
import argparse
import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(HERE, os.pardir, "data", "owntracks_raw.jsonl")

# Meaning + unit per field, from the OwnTracks JSON reference.  Kept here so the
# census is self-describing and the report can cite units without re-deriving.
DICT = {
    "_type": "message type", "lat": "latitude (deg)", "lon": "longitude (deg)",
    "acc": "horizontal accuracy (m)", "alt": "altitude (m ASL)",
    "vac": "vertical accuracy (m)", "vel": "velocity (km/h)",
    "cog": "course over ground (deg)", "batt": "battery (%)",
    "bs": "battery status 0=unknown 1=unplugged 2=charging 3=full",
    "tst": "fix timestamp (epoch s)", "created_at": "message created (epoch s)",
    "tid": "tracker id (2 char)", "topic": "MQTT topic (HTTP only)",
    "conn": "connectivity w=wifi o=offline m=mobile",
    "m": "monitoring mode 1=significant 2=move",
    "p": "barometric pressure (kPa)", "rad": "region radius (m)",
    "t": "trigger p=ping c=region C=beacon b=beacon r=response u=manual t=timer v=monitoring",
    "inregions": "names of regions currently inside",
    "inrids": "ids of regions currently inside",
    "SSID": "wifi network name", "BSSID": "wifi AP MAC",
    # iOS 26.2.3 emits these lowercase; the schema page spells them uppercase.
    "ssid": "wifi network name", "bssid": "wifi AP MAC",
    "steps": "step count in window", "from": "window start (epoch s)",
    "distance": "distance walked in window (m)",
    "floorsup": "floors ascended in window", "floorsdown": "floors descended in window",
    "iOS": "device/OS/permission detail (status reply)",
    "to": "window end (epoch s)", "desc": "region/beacon description",
    "event": "enter|leave", "wtst": "waypoint timestamp (epoch s)",
    "rid": "region id", "uuid": "beacon uuid", "major": "beacon major",
    "minor": "beacon minor", "rssi": "beacon rssi (dBm)",
    "prox": "beacon proximity 0=unknown 1=immediate 2=near 3=far",
    "name": "display name", "face": "avatar (base64 png)",
    "motionactivities": "motion activity (iOS + android)",
    "poi": "point of interest", "tag": "user tag",
    "_id": "internal id", "image": "image", "imagename": "image name",
}


def load(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", default=DEFAULT)
    ap.add_argument("--type", default=None, help="restrict to one _type")
    args = ap.parse_args()

    rows = load(args.jsonl)
    if not rows:
        print("no payloads captured yet")
        return

    by_type = defaultdict(list)
    for r in rows:
        p = r.get("payload")
        if isinstance(p, dict):
            by_type[p.get("_type", "?")].append(p)

    print(f"{len(rows)} payloads  |  types: "
          + ", ".join(f"{t}x{len(v)}" for t, v in sorted(by_type.items())))

    span = [r["payload"].get("tst") for r in rows
            if isinstance(r.get("payload"), dict) and r["payload"].get("tst")]
    if len(span) > 1:
        print(f"tst span: {max(span) - min(span)}s over {len(span)} timestamped msgs")

    for mtype, msgs in sorted(by_type.items()):
        if args.type and mtype != args.type:
            continue
        print(f"\n=== _type={mtype}  ({len(msgs)} messages) ===")
        print(f"{'field':<18}{'n':>5}{'cov':>6}  {'vary':<5} {'observed':<34} meaning")
        print("-" * 118)

        fields = sorted({k for m in msgs for k in m})
        for f in fields:
            vals = [m[f] for m in msgs if f in m]
            uniq = {json.dumps(v, sort_keys=True) for v in vals}
            cov = f"{100 * len(vals) // len(msgs)}%"
            vary = "yes" if len(uniq) > 1 else "-"

            nums = [v for v in vals if isinstance(v, (int, float))
                    and not isinstance(v, bool)]
            if nums and len(uniq) > 1:
                obs = f"{min(nums):g} .. {max(nums):g}"
            else:
                s = str(vals[-1])
                obs = s[:31] + "..." if len(s) > 34 else s

            print(f"{f:<18}{len(vals):>5}{cov:>6}  {vary:<5} {obs:<34} "
                  f"{DICT.get(f, '')}")


if __name__ == "__main__":
    main()

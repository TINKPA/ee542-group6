#!/usr/bin/env python3
"""Pull this handset's position log out of Home Assistant's recorder.

Why this exists: OwnTracks went silent on phoneA for two long stretches on
2026-09-27 (15.9 h and 7.3 h), leaving one isolated fix 53 km east of home and
no path between it and the base.  The same iPhone also runs the Home Assistant
companion app, which reports to a separate recorder on the LAN, and that
recorder kept the drive.

The two are NOT interchangeable and must not be merged into one series:

  OwnTracks  distance-triggered.  On the 2026-09-27 drive, step held at ~55 m
             (CV small) while the interval tracked 50 m / v.
  HA         time-triggered.  Same handset, same drive, same hours: interval
             median 302 s (CV 0.28), step median 3198 m (CV 0.68).

So HA is the control, not a patch: it fixes *time* and lets distance vary,
which is the dual of what OwnTracks does.  Appending HA rows to the OwnTracks
series would destroy the cadence measurement that contrast supports.  Keep them
in separate files, and say which one a number came from.

Credentials: HA_TOKEN comes from personal-vault, never from a file in the repo.

    export HA_TOKEN="$(uv run --quiet --directory ~/Developer/personal-vault \
      --with pyrage python -m personal_vault.query --reveal \
      --reason '<why>' get 'Home Assistant (HAOS)' \
      'Long-Lived Access Token (Claude Setup 2026-05-23)' \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["value"])')"

    python3 code/ha_fetch.py --start 2026-09-22 --end 2026-09-29 \
        --out data/ha_daniels_iphone.jsonl
"""
import argparse
import datetime
import json
import os
import sys
import urllib.request
import zoneinfo

LA = zoneinfo.ZoneInfo("America/Los_Angeles")
HA_URL = os.environ.get("HA_URL", "http://192.168.50.6:8123")
ENTITY = "device_tracker.daniels_iphone"


def fetch(start, end, entity, token):
    q = (f"{HA_URL}/api/history/period/{start}?end_time={end}"
         f"&filter_entity_id={entity}")
    req = urllib.request.Request(q, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)
    return data[0] if data else []


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True, help="YYYY-MM-DD, local (America/Los_Angeles)")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD, exclusive-ish upper bound")
    ap.add_argument("--entity", default=ENTITY)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    token = os.environ.get("HA_TOKEN")
    if not token:
        sys.exit("HA_TOKEN not set; see the docstring for the vault command")

    s = f"{args.start}T00:00:00-07:00"
    e = f"{args.end}T00:00:00-07:00"
    rows = fetch(s, e, args.entity, token)

    n = 0
    with open(args.out, "w") as f:
        for r in rows:
            a = r.get("attributes", {})
            if a.get("latitude") is None:
                continue
            t = datetime.datetime.fromisoformat(r["last_updated"].replace("Z", "+00:00"))
            f.write(json.dumps({
                "source": "home-assistant-recorder",
                "entity_id": args.entity,
                "ts_utc": t.isoformat(),
                "ts_local": t.astimezone(LA).isoformat(),
                "tst": int(t.timestamp()),
                "lat": a["latitude"],
                "lon": a["longitude"],
                "gps_accuracy": a.get("gps_accuracy"),
                "zone_state": r["state"],
                "altitude": a.get("altitude"),
                "vertical_accuracy": a.get("vertical_accuracy"),
                "battery_level": a.get("battery_level"),
                "source_type": a.get("source_type"),
            }) + "\n")
            n += 1
    print(f"{n} rows -> {args.out}")


if __name__ == "__main__":
    main()

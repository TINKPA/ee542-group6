#!/usr/bin/env python3
"""Replay captured OwnTracks payloads into ThingsBoard's device telemetry API.

This is the §4 → §5 leg with the phone taken out of the loop: the payloads are
POSTed to the very endpoint the handset would post to,
POST /api/v1/<DEVICE_TOKEN>/telemetry, one device token per phone (E-12).
It lets the hub, the dashboard and code/rendezvous.py be tested with no AWS
account and no handset.

Sources
  data/owntracks_raw.jsonl       real capture, one iPhone  -> device phoneA
  data/synthetic_phones.jsonl    fabricated (synth_phone.py) -> phoneB, phoneC

Hygiene applied before sending, per Appendix A.5 of the corrected handout:
de-duplicate on (tst, tid), then sort by tst rather than by arrival order.

Payloads go up VERBATIM.  Nothing is flattened or renamed, so what ThingsBoard
stores is exactly what it would store from a phone — which is how `--keys`
below can show which fields survive as telemetry and which are dropped (E-16).

    python3 code/local/replay.py --shift-now
    python3 code/local/replay.py --keys
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tb_api import TB  # noqa: E402

LAB5 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REAL = os.path.join(LAB5, "data", "owntracks_raw.jsonl")
SYNTH = os.path.join(LAB5, "data", "synthetic_phones.jsonl")
DEVICES = os.path.join(LAB5, "code", "local", "tb_devices.json")


def load():
    """-> {device_name: [payload, ...]} with A.5 hygiene applied."""
    per = {}
    if os.path.exists(REAL):
        for line in open(REAL):
            line = line.strip()
            if not line:
                continue
            p = json.loads(line).get("payload") or {}
            if p.get("_type") == "location":
                per.setdefault("phoneA", []).append(p)
    if os.path.exists(SYNTH):
        for line in open(SYNTH):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            per.setdefault(r["device"], []).append(r["payload"])

    clean = {}
    for name, rows in per.items():
        seen, keep = set(), []
        for p in rows:
            key = (p.get("tst"), p.get("tid"))
            if key in seen:
                continue
            seen.add(key)
            keep.append(p)
        keep.sort(key=lambda p: p["tst"])
        clean[name] = keep
        if len(keep) != len(rows):
            print(f"  {name}: dropped {len(rows) - len(keep)} duplicate payload(s)")
    return clean


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shift-now", action="store_true",
                    help="shift every timestamp so the last fix lands at now, "
                         "which puts the track inside a dashboard's default window")
    ap.add_argument("--keys", action="store_true",
                    help="do not send; list which keys the hub kept per device")
    args = ap.parse_args()

    tb = TB()
    tracks = load()

    if args.keys:
        for name in sorted(tracks):
            did = tb.devices().get(name)
            if not did:
                print(f"{name}: not provisioned")
                continue
            sent = sorted({k for p in tracks[name] for k in p})
            stored = sorted(tb.keys(did))
            print(f"\n{name}: sent {len(sent)} fields, hub kept {len(stored)}")
            print("  kept   :", ", ".join(stored))
            print("  dropped:", ", ".join(k for k in sent if k not in stored) or "-")
        return

    tokens = {}
    for name in sorted(tracks):
        did = tb.ensure_device(name, label=(
            "real capture, iPhone" if name == "phoneA" else "SYNTHETIC"))
        tokens[name] = tb.token(did)
    with open(DEVICES, "w") as f:
        json.dump({n: {"token": t, "id": tb.devices()[n]} for n, t in tokens.items()},
                  f, indent=2, sort_keys=True)

    last_tst = max(p["tst"] for rows in tracks.values() for p in rows)
    shift = int(time.time()) - last_tst if args.shift_now else 0
    if shift:
        print(f"shifting all timestamps by {shift} s "
              f"(+{shift / 86400:.1f} days) so the track ends now")

    for name in sorted(tracks):
        rows = [{"ts": (p["tst"] + shift) * 1000, "values": p} for p in tracks[name]]
        for i in range(0, len(rows), 50):
            tb.post_telemetry(tokens[name], rows[i:i + 50])
        span = (rows[-1]["ts"] - rows[0]["ts"]) / 60000
        print(f"{name}: {len(rows)} payloads over {span:.1f} min -> "
              f"token {tokens[name][:6]}…")
    print(f"\ndevice tokens written to {DEVICES}")


if __name__ == "__main__":
    main()

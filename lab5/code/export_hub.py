#!/usr/bin/env python3
"""Pull every phone's full telemetry out of the hub into data/hub_<phone>.jsonl.

The EC2 instance powers itself off on 2026-10-04 and its volume is
DeleteOnTermination, so the hub is not an archive: every figure has to be
reproducible from these files after it is gone.

Schema is one flat object per fix, telemetry values exactly as ThingsBoard
returns them (strings), plus `ts`, the hub's receive time in epoch ms.  That is
what code/analysis/common.py reads, so it is the only export format -- a second
one in a different shape would let two figures disagree about the same fix.

Fetched a day at a time: one range query over ~13k fixes x 23 keys runs past
the server's 50k-value page cap and comes back silently truncated.

    TB_URL=https://<host> python3 code/export_hub.py
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "local"))
from tb_api import TB, TB_URL  # noqa: E402

LAB5 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Read off each handset's Expert Mode screen; telemetry never carries them.
# phoneC's 200 m is the independent variable of the displacement ablation, so
# losing this table would make its data uninterpretable.
SETTINGS = {
    "phoneA": {"locatorInterval": 60, "locatorDisplacement": 50},
    "phoneB": {"locatorInterval": 60, "locatorDisplacement": 50},
    "phoneC": {"locatorInterval": 60, "locatorDisplacement": 200},
}
DAY_MS = 24 * 3600 * 1000


def export(tb, name, did, out_path):
    keys = sorted(tb.keys(did))
    if not keys:
        return 0, None, None
    probe = tb.timeseries(did, ["lat"], 0, int(time.time() * 1000) + DAY_MS)
    stamps = [int(p["ts"]) for p in probe.get("lat", [])]
    if not stamps:
        return 0, None, None
    lo, hi = min(stamps), max(stamps)
    rows = {}
    t = lo - 1
    while t <= hi:
        chunk = tb.timeseries(did, keys, t, min(t + DAY_MS, hi + 1))
        for k, pts in chunk.items():
            for p in pts:
                rows.setdefault(int(p["ts"]), {})[k] = p["value"]
        t += DAY_MS
    with open(out_path, "w") as f:
        for ts in sorted(rows):
            f.write(json.dumps({**rows[ts], "ts": ts}) + "\n")
    return len(rows), lo, hi


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--devices", nargs="*", default=["phoneA", "phoneB", "phoneC"])
    args = ap.parse_args()
    data_dir = os.path.join(LAB5, "data")
    os.makedirs(data_dir, exist_ok=True)

    tb = TB()
    devs = tb.devices()
    md = ["# Lab 5 telemetry export", "",
          f"Source: `{TB_URL}` · exported {time.strftime('%Y-%m-%d %H:%M %Z')}", "",
          "| device | fixes | first (PDT) | last (PDT) | locatorInterval | locatorDisplacement |",
          "|---|---|---|---|---|---|"]
    for name in args.devices:
        if name not in devs:
            print(f"{name}: absent on hub")
            continue
        path = os.path.join(data_dir, f"hub_{name}.jsonl")
        n, lo, hi = export(tb, name, devs[name], path)
        s = SETTINGS.get(name, {})
        fm = lambda x: time.strftime('%m-%d %H:%M', time.localtime(x / 1000)) if x else "-"
        print(f"{name}: {n} fixes -> {path}")
        md.append(f"| {name} | {n} | {fm(lo)} | {fm(hi)} | {s.get('locatorInterval','?')} s | "
                  f"{s.get('locatorDisplacement','?')} m |")
    md += ["", "`ts` is the hub's receive time (epoch ms); `tst` is the handset's own clock.",
           "", "Do not merge with `data/ha_daniels_iphone.jsonl`: that is a time-triggered",
           "sampler on the same handset as phoneA, and mixing the two destroys the",
           "distance-triggered result."]
    with open(os.path.join(data_dir, "EXPORT_MANIFEST.md"), "w") as f:
        f.write("\n".join(md) + "\n")
    print("manifest -> data/EXPORT_MANIFEST.md")


if __name__ == "__main__":
    main()

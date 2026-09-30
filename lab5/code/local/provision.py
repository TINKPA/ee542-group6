#!/usr/bin/env python3
"""Create one ThingsBoard device per phone and print the URL each phone needs.

Until now the devices were created by hand in the UI (§3) or as a side effect
of replay.py, neither of which helps a teammate who has a handset and no
captured data.  This does just the provisioning step, against whichever hub
TB_URL points at, and ends with the exact string to paste into OwnTracks.

One device per phone, never a shared token (errata E-12): the token is the only
thing that tells the hub which handset a payload came from, so two phones on
one token produce a single merged track that cannot be separated afterwards --
which would break §6's multiple-phone requirement.

    TB_URL=https://<host> python3 code/local/provision.py alice bob
    python3 code/local/provision.py              # phoneA phoneB phoneC

Device tokens are written to code/local/tb_devices.json, the same file
replay.py and rendezvous.py read.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tb_api import TB, TB_URL  # noqa: E402

DEVICES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tb_devices.json")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", default=None,
                    help="device names, one per phone (default phoneA phoneB phoneC)")
    ap.add_argument("--label", default="phone",
                    help="ThingsBoard label for the created devices")
    args = ap.parse_args()
    names = args.names or ["phoneA", "phoneB", "phoneC"]

    tb = TB()
    existing = tb.devices()
    out = json.load(open(DEVICES)) if os.path.exists(DEVICES) else {}

    for name in names:
        fresh = name not in existing
        did = tb.ensure_device(name, label=args.label)
        token = tb.token(did)
        out[name] = {"id": did, "token": token}
        print(f"{name:12s} {'created' if fresh else 'exists ':8s} token={token}")

    with open(DEVICES, "w") as f:
        json.dump(out, f, indent=2, sort_keys=True)
    print(f"\ntokens -> {DEVICES}")

    # The OwnTracks HTTP endpoint.  Only the URL field carries the address in
    # HTTP mode -- Host/Port/TLS/Proto are MQTT-only and filling them instead
    # fails as EAI_NONAME, which reads like a DNS outage (errata E-5).
    print("\nOwnTracks -> Preferences -> Connection -> Mode: HTTP, then URL:")
    for name in names:
        print(f"  {name:12s} {TB_URL}/api/v1/{out[name]['token']}/telemetry")
    if TB_URL.startswith("http://"):
        print("\nNOTE: this is a plaintext URL.  OwnTracks for iOS will refuse it "
              "(errata E-6); run code/aws/tb_tls.sh and use the https host.")


if __name__ == "__main__":
    main()

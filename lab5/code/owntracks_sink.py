#!/usr/bin/env python3
"""EE542 Lab 5 — raw OwnTracks HTTP sink.

Captures every payload the phone POSTs, byte-for-byte, into a JSONL file so we
can enumerate exactly which telemetry fields this handset actually emits (the
official schema lists the union over all platforms; only the phone tells us the
truth).  Deliberately dumb: it stores, it does not interpret.

Answers OwnTracks with `[]`, the documented "nothing for you" reply, so the app
treats each POST as delivered and does not queue/retry.

The response is also the only channel back to the phone, so we use it to probe:
queueing a command with `GET /cmd/<action>` makes the next POST reply carry
`[{"_type":"cmd","action":...}]`.  That pulls data the app never volunteers —
`reportSteps` (pedometer), `status` (device/OS/permission detail), `dump`
(entire configuration), `waypoints` (defined regions).  Passive capture alone
badly undercounts what the handset can supply.  Requires "remote commands"
enabled in the app.

  uv run assignments/lab5/code/owntracks_sink.py [--port 8080]

Data lands in ../data/owntracks_raw.jsonl relative to this script (never the
session scratchpad — see the project's no-scratchpad-only-scripts rule).
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, os.pardir, "data", "owntracks_raw.jsonl")
DEFAULT_OUT = OUT

# Header names OwnTracks sets to identify the handset in HTTP mode.
ID_HEADERS = ("x-limit-u", "x-limit-d", "user-agent", "content-type", "authorization")

seen_types: dict[str, int] = {}
seen_fields: dict[str, set] = {}
n_total = 0

# Commands staged for the next POST reply.  reportSteps needs a window, so we
# ask for the last 24h; -1 in the answer means the phone has no pedometer data.
PROBES = {
    "reportLocation": {"_type": "cmd", "action": "reportLocation"},
    "reportSteps": {"_type": "cmd", "action": "reportSteps",
                    "from": int(time.time()) - 86400, "to": int(time.time())},
    "status": {"_type": "cmd", "action": "status"},
    "dump": {"_type": "cmd", "action": "dump"},
    "waypoints": {"_type": "cmd", "action": "waypoints"},
    # Tighten the reporting cadence for data collection.  The handout's defaults
    # (200 m / 180 s) yield two or three points per city block, too coarse to
    # draw a track.  Settings.m:408 fromDictionary is a per-key MERGE -- every
    # key sits behind `if (object)` -- so omitted keys (url, mode, cmd...) are
    # left untouched.  The inner dict must carry _type=configuration or the app
    # rejects it (Settings.m:418).  Gated by the app's remoteConfiguration.
    "dense": {"_type": "cmd", "action": "setConfiguration",
              "configuration": {"_type": "configuration",
                                "locatorDisplacement": 50,
                                "locatorInterval": 60}},
    # Restore the values the handout's walkthrough leaves in place.
    "coarse": {"_type": "cmd", "action": "setConfiguration",
               "configuration": {"_type": "configuration",
                                 "locatorDisplacement": 200,
                                 "locatorInterval": 180}},
}
pending: list = []


def record(entry: dict) -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # silence the default stderr spam
        pass

    def _reply(self, code: int, body: bytes = b"[]") -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/cmd/"):
            action = self.path[len("/cmd/"):].strip("/")
            if action not in PROBES:
                self._reply(404, f"unknown probe: {action}\n"
                                 f"try: {' '.join(PROBES)}\n".encode())
                return
            pending.append(PROBES[action])
            self._reply(200, f"queued {action}; "
                             f"{len(pending)} pending\n".encode())
            return

        # A browser-visible census so we can watch coverage grow live.
        lines = [f"owntracks sink — {n_total} payloads captured", ""]
        for t in sorted(seen_types):
            lines.append(f"[{t}]  x{seen_types[t]}")
            lines.append("    " + "  ".join(sorted(seen_fields.get(t, ()))))
            lines.append("")
        self._reply(200, "\n".join(lines).encode())

    def do_POST(self):
        global n_total
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""

        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            payload, parse_error = None, f"{type(exc).__name__}: {exc}"
        else:
            parse_error = None

        # OwnTracks normally sends one object; tolerate a batched array too.
        items = payload if isinstance(payload, list) else [payload]

        for item in items:
            n_total += 1
            mtype = item.get("_type", "?") if isinstance(item, dict) else "?"
            seen_types[mtype] = seen_types.get(mtype, 0) + 1
            if isinstance(item, dict):
                seen_fields.setdefault(mtype, set()).update(item.keys())

            record({
                "recv_at": datetime.now(timezone.utc).isoformat(),
                "recv_mono": time.monotonic(),
                "peer": self.client_address[0],
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()
                            if k.lower() in ID_HEADERS},
                "parse_error": parse_error,
                "raw": raw.decode("utf-8", "replace") if parse_error else None,
                "payload": item,
            })

            fields = sorted(item.keys()) if isinstance(item, dict) else []
            print(f"#{n_total:<4} {mtype:<12} {len(fields):>2} fields  "
                  f"{' '.join(fields)}", flush=True)

        # Drain the probe queue into this reply — our only channel to the phone.
        out, pending[:] = list(pending), []
        if out:
            print(f"  -> sending {len(out)} cmd: "
                  f"{[c['action'] for c in out]}", flush=True)
        self._reply(200, json.dumps(out).encode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="capture file; point it elsewhere when smoke-testing "
                         "so the real capture is not appended to")
    args = ap.parse_args()
    global OUT
    OUT = args.out

    srv = ThreadingHTTPServer((args.bind, args.port), Handler)
    print(f"listening on {args.bind}:{args.port}  ->  {os.path.normpath(OUT)}",
          flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print(f"\nstopped after {n_total} payloads", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

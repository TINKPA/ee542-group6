#!/usr/bin/env python3
"""Minimal ThingsBoard CE REST client — the handful of calls Lab 5 needs.

stdlib only, so the same file runs on the EC2 node (§2) and against the local
VM (code/local/lima-tb.yaml) with nothing installed.

    TB_URL   default http://localhost:8080
    TB_USER  default tenant@thingsboard.org
    TB_PASS  default tenant

Used as a library by provision.py / replay.py / rendezvous.py, and directly:

    python3 tb_api.py devices
    python3 tb_api.py token phoneA
"""
import json
import os
import sys
import urllib.error
import urllib.request

TB_URL = os.environ.get("TB_URL", "http://localhost:8080").rstrip("/")
TB_USER = os.environ.get("TB_USER", "tenant@thingsboard.org")
TB_PASS = os.environ.get("TB_PASS", "tenant")


class TB:
    def __init__(self, url=TB_URL, user=TB_USER, password=TB_PASS):
        self.url = url.rstrip("/")
        self.jwt = self._call("POST", "/api/auth/login",
                              {"username": user, "password": password},
                              auth=False)["token"]

    # --- plumbing ------------------------------------------------------------
    def _call(self, method, path, body=None, auth=True):
        req = urllib.request.Request(self.url + path, method=method)
        req.add_header("Content-Type", "application/json")
        if auth:
            req.add_header("X-Authorization", "Bearer " + self.jwt)
        data = json.dumps(body).encode() if body is not None else None
        try:
            with urllib.request.urlopen(req, data, timeout=60) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path} -> {e.code} {e.read()[:400]!r}") from None
        return json.loads(raw) if raw else None

    # --- devices -------------------------------------------------------------
    def devices(self):
        """All tenant devices, as {name: id}."""
        page = self._call("GET", "/api/tenant/devices?pageSize=1000&page=0")
        return {d["name"]: d["id"]["id"] for d in page["data"]}

    def ensure_device(self, name, label=None):
        """Create the device if it is not there yet; return its id."""
        existing = self.devices()
        if name in existing:
            return existing[name]
        d = self._call("POST", "/api/device",
                       {"name": name, "type": "default", "label": label or name})
        return d["id"]["id"]

    def token(self, device_id):
        """The device access token — the only thing identifying a phone (E-12)."""
        return self._call("GET", f"/api/device/{device_id}/credentials")["credentialsId"]

    # --- telemetry -----------------------------------------------------------
    def post_telemetry(self, token, rows):
        """rows: [{"ts": <epoch ms>, "values": {...}}, ...] — the same endpoint
        the phone posts to, so this exercises the real ingestion path."""
        req = urllib.request.Request(f"{self.url}/api/v1/{token}/telemetry",
                                     method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, json.dumps(rows).encode(), timeout=60) as r:
            return r.status

    def timeseries(self, device_id, keys, start_ms, end_ms, limit=50000):
        """Read back what the hub stored. agg=NONE keeps every sample."""
        q = (f"/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries"
             f"?keys={','.join(keys)}&startTs={start_ms}&endTs={end_ms}"
             f"&limit={limit}&agg=NONE&orderBy=ASC")
        return self._call("GET", q)

    def latest(self, device_id):
        return self._call(
            "GET", f"/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries")

    def keys(self, device_id):
        return self._call(
            "GET", f"/api/plugins/telemetry/DEVICE/{device_id}/keys/timeseries")

    def set_attributes(self, device_id, attrs):
        return self._call(
            "POST", f"/api/plugins/telemetry/DEVICE/{device_id}/SERVER_SCOPE", attrs)

    # --- dashboards ----------------------------------------------------------
    def dashboards(self):
        page = self._call("GET", "/api/tenant/dashboards?pageSize=1000&page=0")
        return {d["title"]: d["id"]["id"] for d in page["data"]}

    def save_dashboard(self, dashboard):
        return self._call("POST", "/api/dashboard", dashboard)

    def get_dashboard(self, dashboard_id):
        return self._call("GET", f"/api/dashboard/{dashboard_id}")


def main(argv):
    tb = TB()
    if not argv or argv[0] == "devices":
        for name, did in sorted(tb.devices().items()):
            print(f"{name:20s} {did}  token={tb.token(did)}")
    elif argv[0] == "token":
        print(tb.token(tb.devices()[argv[1]]))
    elif argv[0] == "keys":
        print(", ".join(tb.keys(tb.devices()[argv[1]])))
    elif argv[0] == "latest":
        print(json.dumps(tb.latest(tb.devices()[argv[1]]), indent=2))
    elif argv[0] == "dashboards":
        for t, i in tb.dashboards().items():
            print(f"{t:30s} {i}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])

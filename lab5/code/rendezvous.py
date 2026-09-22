#!/usr/bin/env python3
"""Rendezvous — the §6 custom mapping program.

§6 asks for "some sort of interesting mapping solution using multiple phone
data".  This is the multiple-phone part taken literally: it reads every phone's
track out of the ThingsBoard hub and answers a question one phone cannot —
**when were two team members in the same place, and for how long?**

Pipeline
    hub (REST)  ->  hygiene  ->  common time grid  ->  pairwise distance
                ->  encounter detection  ->  back into the hub + a web map

Why each step is there
  * Hygiene (Appendix A.5): de-duplicate on (tst, tid) and sort by tst.  One of
    29 real payloads was a byte-identical repeat, and queued payloads arrive out
    of order, both of which would fake up distance.
  * Common grid: the phones report on their own ~60 s timers (E-14) and are
    never in step, so two tracks have no shared timestamps at all.  Each track
    is sampled onto one grid by carrying the last fix forward, but only while it
    is fresher than --max-age; past that the phone's position is unknown rather
    than assumed.  Without the staleness cut, a phone that stopped reporting
    "stays" next to the other one forever.
  * Accuracy-aware threshold: the hub stores the phone's own error estimate in
    `acc`.  Two phones count as together when
        haversine(a, b) - acc_a - acc_b  <=  --radius
    i.e. only when the claim survives both error bars.  A fixed 50 m rule would
    call a pair together on nothing but GPS noise.
  * Hysteresis: an encounter opens only after --min-samples consecutive
    together-samples and closes after the same number apart, and is kept only
    if it lasted --min-duration.  A single bad fix cannot create an event.

Outputs
  * out/rendezvous.json      the encounter list
  * out/rendezvous_map.html  self-contained Leaflet map: one track per phone,
                             encounter markers, pairwise-distance chart
  * device `team-rendezvous` in the hub: per-pair distance as telemetry (so it
    plots in a ThingsBoard chart) and the encounter list as a server attribute.
    The derived product lives in the hub, not on the laptop that computed it.

    python3 code/rendezvous.py
    python3 code/rendezvous.py --radius 40 --max-age 240
"""
import argparse
import itertools
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "local"))
from tb_api import TB  # noqa: E402

LAB5 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(LAB5, "out")
COLORS = ["#d62728", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf"]
KEYS = ["lat", "lon", "acc", "vel", "batt", "conn", "motionactivities"]


def haversine(lat1, lon1, lat2, lon2):
    r = 6_371_008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def fetch(tb, names):
    """-> {phone: [ {ts, lat, lon, acc, ...}, ... ]} straight out of the hub."""
    devices = tb.devices()
    tracks = {}
    now_ms = int(time.time() * 1000)
    for name in names:
        if name not in devices:
            continue
        raw = tb.timeseries(devices[name], KEYS, 0, now_ms + 86_400_000)
        by_ts = {}
        for key, points in raw.items():
            for pt in points:
                by_ts.setdefault(int(pt["ts"]), {})[key] = pt["value"]
        rows = []
        for ts, vals in by_ts.items():
            if "lat" not in vals or "lon" not in vals:
                continue
            rows.append({
                "ts": ts,
                "lat": float(vals["lat"]), "lon": float(vals["lon"]),
                "acc": float(vals.get("acc", 0) or 0),
                "vel": vals.get("vel"), "batt": vals.get("batt"),
                "conn": vals.get("conn"),
                "motion": (vals.get("motionactivities") or "").strip('[]"'),
            })
        # A.5 hygiene: de-duplicate, then order by time rather than by arrival.
        seen, clean = set(), []
        for r in sorted(rows, key=lambda r: r["ts"]):
            k = (r["ts"], round(r["lat"], 6), round(r["lon"], 6))
            if k in seen:
                continue
            seen.add(k)
            clean.append(r)
        if clean:
            tracks[name] = clean
    return tracks


def resample(track, grid, max_age_ms):
    """Last fix carried forward, but only while it is fresher than max_age."""
    out, i, cur = [], 0, None
    for t in grid:
        while i < len(track) and track[i]["ts"] <= t:
            cur = track[i]
            i += 1
        out.append(cur if cur and t - cur["ts"] <= max_age_ms else None)
    return out


def encounters(grid, a, b, radius, min_samples, min_duration_s):
    """Hysteresis over the together/apart sequence; returns closed encounters."""
    events, run_open, run_shut, start, samples = [], 0, 0, None, []
    for t, pa, pb in zip(grid, a, b):
        together = False
        d = None
        if pa and pb:
            d = haversine(pa["lat"], pa["lon"], pb["lat"], pb["lon"])
            together = (d - pa["acc"] - pb["acc"]) <= radius
        if together:
            run_open, run_shut = run_open + 1, 0
            samples.append((t, d, pa, pb))
            if start is None and run_open >= min_samples:
                start = samples[0][0]
        else:
            run_shut, run_open = run_shut + 1, 0
            if start is not None and run_shut >= min_samples:
                events.append(close(start, samples, min_duration_s))
                start, samples = None, []
            elif start is None:
                samples = []
    if start is not None:
        events.append(close(start, samples, min_duration_s))
    return [e for e in events if e]


def close(start, samples, min_duration_s):
    end = samples[-1][0]
    if (end - start) / 1000 < min_duration_s:
        return None
    ds = [s[1] for s in samples]
    lats = [s[2]["lat"] for s in samples] + [s[3]["lat"] for s in samples]
    lons = [s[2]["lon"] for s in samples] + [s[3]["lon"] for s in samples]
    return {
        "start_ms": start, "end_ms": end,
        "duration_s": int((end - start) / 1000),
        "min_distance_m": round(min(ds), 1),
        "mean_distance_m": round(sum(ds) / len(ds), 1),
        "samples": len(samples),
        "lat": round(sum(lats) / len(lats), 6),
        "lon": round(sum(lons) / len(lons), 6),
    }


def la(ms):
    """Report every instant in Los Angeles time — the phones and the lab are there."""
    os.environ.setdefault("TZ", "America/Los_Angeles")
    time.tzset()
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def publish(tb, grid, series, events, cfg):
    """Push the derived product back into the hub as its own device."""
    did = tb.ensure_device("team-rendezvous", label="derived by code/rendezvous.py")
    token = tb.token(did)
    rows = []
    for idx, t in enumerate(grid):
        values = {}
        for pair, dists in series.items():
            if dists[idx] is not None:
                values[f"dist_{pair}"] = round(dists[idx], 1)
        if values:
            values["pairs_tracked"] = len(values)
            rows.append({"ts": t, "values": values})
    for i in range(0, len(rows), 50):
        tb.post_telemetry(token, rows[i:i + 50])
    tb.set_attributes(did, {
        "encounters": json.dumps(events),
        "encounter_count": len(events),
        "computed_at": la(int(time.time() * 1000)) + " PDT",
        "config": json.dumps(cfg),
    })
    return did, len(rows)


def render(path, tracks, events, grid, series, cfg):
    payload = {
        "tracks": {n: [[r["ts"], r["lat"], r["lon"], r["acc"],
                        r.get("motion") or "", r.get("batt"), r.get("conn")]
                       for r in rows] for n, rows in tracks.items()},
        "events": events,
        "grid": grid,
        "series": {k: [None if v is None else round(v, 1) for v in vs]
                   for k, vs in series.items()},
        "colors": {n: COLORS[i % len(COLORS)] for i, n in enumerate(sorted(tracks))},
        "cfg": cfg,
    }
    html = HTML.replace("__DATA__", json.dumps(payload))
    with open(path, "w") as f:
        f.write(html)


HTML = r"""<!doctype html>
<meta charset="utf-8">
<title>EE542 Lab 5 — Rendezvous</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  :root { --fg:#1b1b1b; --muted:#666; --line:#dcdcdc; --bg:#fff; }
  body { margin:0; font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
         color:var(--fg); background:var(--bg); }
  header { padding:14px 18px; border-bottom:1px solid var(--line); }
  h1 { margin:0; font-size:17px; }
  header p { margin:4px 0 0; color:var(--muted); font-size:13px; }
  #map { height:56vh; }
  .panel { padding:14px 18px; }
  table { border-collapse:collapse; width:100%; font-size:13px; }
  th,td { text-align:left; padding:6px 10px; border-bottom:1px solid var(--line); }
  th { color:var(--muted); font-weight:600; }
  .chip { display:inline-block; width:10px; height:10px; border-radius:50%;
          margin-right:6px; vertical-align:middle; }
  .warn { background:#fff6e5; border:1px solid #f0c987; padding:8px 12px;
          border-radius:6px; font-size:13px; margin-top:10px; }
  svg text { font-size:10px; fill:var(--muted); }
</style>
<header>
  <h1>Rendezvous — who was where, together, and for how long</h1>
  <p id="sub"></p>
</header>
<div id="map"></div>
<div class="panel">
  <h3 style="margin:0 0 8px">Pairwise distance</h3>
  <div id="chart"></div>
  <h3 style="margin:18px 0 8px">Encounters</h3>
  <table id="tbl"><thead><tr><th>pair</th><th>from</th><th>to</th>
    <th>duration</th><th>closest</th><th>mean</th><th>samples</th></tr></thead>
    <tbody></tbody></table>
  <div class="warn" id="synth" hidden></div>
</div>
<script>
const D = __DATA__;
const fmt = ms => new Date(ms).toLocaleString('en-US',
  {timeZone:'America/Los_Angeles', hour12:false});

const map = L.map('map');
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom:19, attribution:'&copy; OpenStreetMap'}).addTo(map);

const bounds = [];
for (const [name, rows] of Object.entries(D.tracks)) {
  const color = D.colors[name];
  const pts = rows.map(r => [r[1], r[2]]);
  pts.forEach(p => bounds.push(p));
  L.polyline(pts, {color, weight:3, opacity:.85}).addTo(map);
  rows.forEach(r => L.circleMarker([r[1], r[2]], {radius:3, color,
      fillColor:color, fillOpacity:.8, weight:1})
    .bindPopup(`<b>${name}</b><br>${fmt(r[0])}<br>acc ${r[3]} m`
               + `<br>${r[4]||''} · batt ${r[5]??'?'}% · link ${r[6]||'?'}`)
    .addTo(map));
  L.marker(pts[pts.length-1]).addTo(map).bindTooltip(name, {permanent:true,
    direction:'right', className:'lbl'});
}
D.events.forEach(e => {
  const r = Math.max(12, Math.min(40, e.duration_s/30));
  L.circle([e.lat, e.lon], {radius:r, color:'#111', weight:2, dashArray:'4 3',
    fillColor:'#ffd54f', fillOpacity:.45}).addTo(map)
   .bindPopup(`<b>${e.pair}</b><br>${fmt(e.start_ms)} → ${fmt(e.end_ms)}`
              + `<br>${Math.round(e.duration_s/60)} min, closest `
              + `${e.min_distance_m} m`);
  bounds.push([e.lat, e.lon]);
});
map.fitBounds(bounds, {padding:[30,30]});

document.getElementById('sub').textContent =
  `${Object.keys(D.tracks).length} phones · ${D.events.length} encounters · `
  + `together = separation − both accuracy claims ≤ ${D.cfg.radius} m, `
  + `held for ≥ ${D.cfg.min_duration_s} s · times in America/Los_Angeles`;

const tb = document.querySelector('#tbl tbody');
D.events.sort((a,b)=>a.start_ms-b.start_ms).forEach(e => {
  const tr = document.createElement('tr');
  tr.innerHTML = `<td>${e.pair}</td><td>${fmt(e.start_ms)}</td>`
    + `<td>${fmt(e.end_ms)}</td><td>${Math.round(e.duration_s/60)} min</td>`
    + `<td>${e.min_distance_m} m</td><td>${e.mean_distance_m} m</td>`
    + `<td>${e.samples}</td>`;
  tb.appendChild(tr);
});
if (!D.events.length) tb.innerHTML = '<tr><td colspan="7">none</td></tr>';

// distance-vs-time, plain SVG
const W=900, H=220, P={l:46,r:12,t:10,b:24};
// log y: the pairs span ~5 m to ~1 km, and the threshold that decides an
// encounter sits at the bottom of that range — linear would hide it.
const all = Object.values(D.series).flat().filter(v=>v!=null);
const lo = 5, hi = Math.max(100, ...all), t0=D.grid[0], t1=D.grid[D.grid.length-1];
const x = t => P.l + (t-t0)/(t1-t0)*(W-P.l-P.r);
const y = v => { const c = Math.max(lo, v);
  return H-P.b - (Math.log10(c/lo)/Math.log10(hi/lo))*(H-P.t-P.b); };
let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%">`;
[5,10,25,50,100,250,500,1000].filter(v=>v<=hi).forEach(v=>{
  svg += `<line x1="${P.l}" x2="${W-P.r}" y1="${y(v)}" y2="${y(v)}" `
       + `stroke="#eee"/><text x="4" y="${y(v)+4}">${v} m</text>`;});
svg += `<line x1="${P.l}" x2="${W-P.r}" y1="${y(D.cfg.radius)}" `
     + `y2="${y(D.cfg.radius)}" stroke="#f0a" stroke-dasharray="4 3"/>`
     + `<text x="${W-P.r-92}" y="${y(D.cfg.radius)-4}" fill="#f0a">`
     + `together threshold</text>`;
let ci=0;
for (const [pair, vs] of Object.entries(D.series)) {
  const col = ['#7b1fa2','#00796b','#c62828','#1565c0'][ci++%4];
  let d='', pen=false;
  vs.forEach((v,i)=>{ if(v==null){pen=false;return;}
    d += (pen?'L':'M') + x(D.grid[i]) + ' ' + y(v) + ' '; pen=true; });
  svg += `<path d="${d}" fill="none" stroke="${col}" stroke-width="1.8"/>`;
  svg += `<text x="${P.l+6}" y="${10+ci*13}" fill="${col}">${pair}</text>`;
}
svg += `<text x="${P.l}" y="${H-6}">${fmt(t0)}</text>`
     + `<text x="${W-P.r-120}" y="${H-6}">${fmt(t1)}</text></svg>`;
document.getElementById('chart').innerHTML = svg;

if (D.cfg.synthetic_devices && D.cfg.synthetic_devices.length) {
  const el = document.getElementById('synth');
  el.hidden = false;
  el.textContent = 'Synthetic data: ' + D.cfg.synthetic_devices.join(', ')
    + ' are generated by code/local/synth_phone.py, not measured. '
    + 'Encounters involving them demonstrate the detector; they are not '
    + 'observations.';
}
</script>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phones", nargs="*", default=None,
                    help="device names (default: every device named phone*)")
    ap.add_argument("--radius", type=float, default=25.0,
                    help="metres of separation still counted as together, "
                         "AFTER both phones' own accuracy is subtracted")
    ap.add_argument("--step", type=int, default=30, help="time grid, seconds")
    ap.add_argument("--max-age", type=int, default=180,
                    help="seconds a fix may be carried forward before the "
                         "phone counts as position-unknown")
    ap.add_argument("--min-samples", type=int, default=2,
                    help="consecutive samples needed to open or close")
    ap.add_argument("--min-duration", type=int, default=60,
                    help="shortest encounter kept, seconds")
    ap.add_argument("--no-publish", action="store_true",
                    help="skip writing the result back into the hub")
    args = ap.parse_args()

    tb = TB()
    names = args.phones or sorted(n for n in tb.devices() if n.startswith("phone"))
    tracks = fetch(tb, names)
    if len(tracks) < 2:
        sys.exit(f"need at least two phones with lat/lon; found {list(tracks)}")

    start = min(rows[0]["ts"] for rows in tracks.values())
    end = max(rows[-1]["ts"] for rows in tracks.values())
    grid = list(range(start, end + 1, args.step * 1000))
    sampled = {n: resample(rows, grid, args.max_age * 1000)
               for n, rows in tracks.items()}

    series, events = {}, []
    for a, b in itertools.combinations(sorted(tracks), 2):
        pair = f"{a}_{b}"
        series[pair] = [
            haversine(pa["lat"], pa["lon"], pb["lat"], pb["lon"])
            if pa and pb else None
            for pa, pb in zip(sampled[a], sampled[b])]
        for e in encounters(grid, sampled[a], sampled[b], args.radius,
                            args.min_samples, args.min_duration):
            e["pair"] = pair
            events.append(e)

    synthetic = [n for n in tracks if n != "phoneA"]
    cfg = {"radius": args.radius, "step_s": args.step, "max_age_s": args.max_age,
           "min_samples": args.min_samples, "min_duration_s": args.min_duration,
           "synthetic_devices": synthetic}

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "rendezvous.json"), "w") as f:
        json.dump({"config": cfg, "phones": {n: len(r) for n, r in tracks.items()},
                   "encounters": events}, f, indent=1)
    render(os.path.join(OUT, "rendezvous_map.html"), tracks, events, grid, series, cfg)

    print(f"{len(tracks)} phones, {sum(len(r) for r in tracks.values())} fixes, "
          f"grid {len(grid)} x {args.step}s "
          f"({la(start)} → {la(end)} PDT)")
    for e in sorted(events, key=lambda e: e["start_ms"]):
        print(f"  {e['pair']:>16s}  {la(e['start_ms'])} → "
              f"{la(e['end_ms'])[11:]}  {round(e['duration_s'] / 60):3d} min  "
              f"closest {e['min_distance_m']:5.1f} m  ({e['samples']} samples)")
    if not events:
        print("  no encounters")
    if not args.no_publish:
        did, n = publish(tb, grid, series, events, cfg)
        print(f"published {n} distance rows + {len(events)} encounters to "
              f"device team-rendezvous ({did[:8]}…)")
    print(f"map: {os.path.join(OUT, 'rendezvous_map.html')}")


if __name__ == "__main__":
    main()

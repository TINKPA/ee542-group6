#!/usr/bin/env python3
"""Per-day atlas: one small map per phone-day that actually went somewhere.

Days under --min-km are left to the table; drawing a map of a phone that did
not move wastes a panel.  Within a day the track is cut wherever the gap
exceeds GAP_HOLE_S, so an unsampled stretch is a break in the line rather than
a road the phone never drove.

Rendered headless on this machine and saved as PNG: the report needs a static
figure, and a published HTML would re-fetch map tiles on whatever machine
opened it.

    python3 code/make_atlas.py --out report/figures
"""
import argparse
import csv
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from figs_common import load, stops, local_day, GAP_HOLE_S

TPL = """<!DOCTYPE html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
 body{margin:0;background:#fff;font:12px system-ui}
 .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;padding:8px}
 .cell{position:relative}
 .map{height:300px;border:1px solid #d0d7de}
 .lab{position:absolute;top:4px;left:4px;z-index:500;background:rgba(255,255,255,.9);
      padding:1px 6px;border-radius:3px;font-weight:600;font-family:monospace}
</style></head><body>
<div class="grid" id="g"></div>
<script>
var PANELS=__PANELS__;
var g=document.getElementById('g');
PANELS.forEach(function(p,i){
  var c=document.createElement('div'); c.className='cell';
  c.innerHTML='<div class="lab">'+p.label+'</div><div class="map" id="m'+i+'"></div>';
  g.appendChild(c);
});
PANELS.forEach(function(p,i){
  var m=L.map('m'+i,{zoomControl:false,attributionControl:(i===PANELS.length-1)});
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,
    attribution:'&copy; OpenStreetMap'}).addTo(m);
  var all=[];
  p.segs.forEach(function(s){ if(s.length>1) all.push(L.polyline(s,{color:'#d1342f',weight:2.5,opacity:.85}).addTo(m)); });
  p.stops.forEach(function(s){ L.circleMarker([s[0],s[1]],{radius:Math.max(4,Math.min(14,3+Math.sqrt(s[2])*3)),
    color:'#1f6feb',fillColor:'#4f9dfb',fillOpacity:.6,weight:1.5}).addTo(m); });
  if(all.length) m.fitBounds(L.featureGroup(all).getBounds().pad(0.15));
  else if(p.stops.length) m.setView([p.stops[0][0],p.stops[0][1]],14);
});
</script></body></html>"""


def panels(days):
    out = []
    cache = {}
    for dev, day in days:
        if dev not in cache:
            rows = load(dev)
            cache[dev] = (rows, stops(rows))
        rows, st = cache[dev]
        sel = [r for r in rows if local_day(r["t"]) == day]
        segs, cur = [], []
        for i, r in enumerate(sel):
            if cur and r["t"] - sel[i - 1]["t"] > GAP_HOLE_S:
                segs.append(cur)
                cur = []
            cur.append([r["lat"], r["lon"]])
        if cur:
            segs.append(cur)
        sp = [[s["lat"], s["lon"], s["dur"] / 3600.0]
              for s in st if local_day(s["start"]) == day]
        out.append({"label": f"{dev[-1]}  {day[5:]}", "segs": segs, "stops": sp})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="report/figures")
    args = ap.parse_args()
    days = []
    with open(os.path.join(args.out, "atlas_days.csv")) as f:
        for r in csv.DictReader(f):
            days.append((r["device"], r["day"]))
    P = panels(days)
    html = TPL.replace("__PANELS__", json.dumps(P))
    hp = os.path.join(args.out, "_atlas.html")
    open(hp, "w").write(html)

    from playwright.sync_api import sync_playwright
    png = os.path.join(args.out, "atlas.png")
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 980, "height": 1100}, device_scale_factor=2)
        pg.goto(pathlib.Path(hp).resolve().as_uri())
        pg.wait_for_timeout(16000)
        pg.screenshot(path=png, full_page=True)
        b.close()
    print(f"{len(P)} panels -> {png}")


if __name__ == "__main__":
    main()

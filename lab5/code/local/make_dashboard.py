#!/usr/bin/env python3
"""Build the §5 IoT-hub dashboard over the REST API, for all phones at once.

§5 of the handout walks the dashboard through the UI: Dashboards → + → Add new
widget → Maps → OpenStreetMap → data keys lat / lon.  That is fine for one
phone and one demo, but it is not reproducible and it does not survive the EC2
instance being torn down.  This builds the same thing as a JSON artefact:

  * an entity alias that matches every device whose name starts with "phone",
    so the dashboard needs no edit when it is imported on another hub;
  * a Map widget — live position of every phone, OpenStreetMap tiles;
  * a Trip Map widget — the tracks themselves, with the path drawn;
  * a latest-telemetry table.

Widget skeletons are read from the hub's own widget types at run time, so the
config always matches the installed ThingsBoard version rather than a version
guessed at while writing this.

    python3 code/local/make_dashboard.py                 # create / update
    python3 code/local/make_dashboard.py --export out.json

The exported JSON is what gets imported on the EC2 hub (Dashboards → + →
Import dashboard).
"""
import argparse
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tb_api import TB  # noqa: E402

TITLE = "EE542 Lab 5 — Phone fleet"
ALIAS_ID = "11111111-1111-4111-8111-111111111111"   # fixed, so re-runs update
MAP_ID = "22222222-2222-4222-8222-222222222222"
TRIP_ID = "33333333-3333-4333-8333-333333333333"
TABLE_ID = "44444444-4444-4444-8444-444444444444"
CHART_ID = "55555555-5555-4555-8555-555555555555"
RDV_ALIAS_ID = "66666666-6666-4666-8666-666666666666"

# Tile layers.  The handout's §5 asks for the OpenStreetMap widget; in 4.3 the
# map widget takes a layer list instead, and an empty list renders a blank pane.
LAYERS = [
    {"label": "OpenStreetMap", "provider": "openstreet",
     "layerType": "OpenStreetMap.Mapnik"},
    {"label": "Satellite", "provider": "openstreet",
     "layerType": "Esri.WorldImagery"},
]

TOOLTIP = ("<b>${entityName}</b><br/>"
           "<b>lat/lon:</b> ${latitude:6}, ${longitude:6}<br/>"
           "<b>speed:</b> ${vel} km/h &nbsp; <b>fix acc:</b> ${acc} m<br/>"
           "<b>battery:</b> ${batt}% &nbsp; <b>link:</b> ${conn}<br/>"
           "<b>motion:</b> ${motionactivities}")


def ts_key(name, label=None, color="#2196f3"):
    return {"name": name, "type": "timeseries", "label": label or name,
            "color": color, "settings": {}, "aggregationType": "NONE",
            "units": None, "decimals": None, "funcBody": None,
            "usePostProcessing": None, "postFuncBody": None}


def entity_source(template, extra_keys):
    """Turn a demo 'function' marker/trip into one backed by the phone alias."""
    src = json.loads(json.dumps(template))
    src.update({
        "dsType": "entity",
        "dsLabel": "",
        "dsDeviceId": None,
        "dsEntityAliasId": ALIAS_ID,
        "dsFilterId": None,
        "additionalDataKeys": [ts_key(k) for k in extra_keys],
        "xKey": ts_key("lat", "latitude"),
        "yKey": ts_key("lon", "longitude"),
        "label": {"show": True, "type": "pattern", "pattern": "${entityName}"},
        "tooltip": {"show": True, "trigger": "click", "autoclose": True,
                    "type": "pattern", "pattern": TOOLTIP,
                    "offsetX": 0, "offsetY": -1},
    })
    return src


def widget(tb, wid, fqn, type_id, title, settings_patch, is_timeseries=False):
    wt = tb._call("GET", f"/api/widgetType/{type_id}")
    cfg = json.loads(wt["descriptor"]["defaultConfig"])
    cfg["title"] = title
    cfg["showTitle"] = True
    cfg["datasources"] = []          # the map widgets subscribe via settings
    cfg["settings"].update(settings_patch)
    w = {"id": wid, "typeFullFqn": f"system.{fqn}", "type": wt["descriptor"]["type"],
         "sizeX": wt["descriptor"]["sizeX"], "sizeY": wt["descriptor"]["sizeY"],
         "row": 0, "col": 0, "config": cfg}
    if is_timeseries:
        # Follow the dashboard's own window, so the toolbar clock governs every
        # widget at once -- including live, on camera, during the demo.  This
        # only works because the dashboard window below is a *history* window:
        # a trip widget pointed at a realtime window reports "No trips data
        # available".  The two settings are a pair; changing one breaks the map.
        cfg["useDashboardTimewindow"] = True
        cfg["displayTimewindow"] = True
    return w


def build(tb):
    wmap = tb._call("GET", "/api/widgetTypes?pageSize=1000&page=0")
    ids = {w["fqn"]: w["id"]["id"] for w in wmap["data"]}
    for fqn in ("map", "trip_map", "cards.entities_table", "time_series_chart"):
        if fqn not in ids:
            sys.exit(f"widget type {fqn} not found on this hub")

    map_default = json.loads(
        tb._call("GET", f"/api/widgetType/{ids['map']}")["descriptor"]["defaultConfig"])
    trip_default = json.loads(
        tb._call("GET", f"/api/widgetType/{ids['trip_map']}")["descriptor"]["defaultConfig"])

    marker = entity_source(map_default["settings"]["markers"][0],
                           ["batt", "vel", "acc", "conn", "motionactivities"])
    trip = entity_source(trip_default["settings"]["trips"][0],
                         ["batt", "vel", "acc", "conn", "motionactivities"])
    trip.update({"showPath": True, "pathStrokeWeight": 4,
                 "showPoints": True, "pointSize": 8})

    widgets = {
        MAP_ID: widget(tb, MAP_ID, "map", ids["map"], "Where the phones are now",
                       {"markers": [marker], "layers": LAYERS,
                        "fitMapBounds": True}),
        TRIP_ID: widget(tb, TRIP_ID, "trip_map", ids["trip_map"], "Tracks",
                        {"trips": [trip], "layers": LAYERS,
                         "fitMapBounds": True},
                        is_timeseries=True),
        TABLE_ID: widget(tb, TABLE_ID, "cards.entities_table",
                         ids["cards.entities_table"], "Latest telemetry", {}),
        # code/rendezvous.py writes its pairwise distances back into the hub as
        # ordinary telemetry, so the §6 result is readable from the dashboard
        # and not only from the program that produced it.
        CHART_ID: widget(tb, CHART_ID, "time_series_chart",
                         ids["time_series_chart"],
                         "Pairwise distance (from code/rendezvous.py)", {}),
    }
    ccfg = widgets[CHART_ID]["config"]
    ccfg["datasources"] = [{
        "type": "entity", "name": None, "entityAliasId": RDV_ALIAS_ID,
        "filterId": None,
        "dataKeys": [ts_key(k, c) for k, c in (
            ("dist_phoneA_phoneB", "#7b1fa2"), ("dist_phoneA_phoneC", "#00796b"),
            ("dist_phoneB_phoneC", "#c62828"))],
    }]
    for dk, col in zip(ccfg["datasources"][0]["dataKeys"],
                       ("#7b1fa2", "#00796b", "#c62828")):
        dk["color"] = col
    ccfg["useDashboardTimewindow"] = True
    ccfg["displayTimewindow"] = True
    # the table is a plain entity-datasource widget, not a map
    tcfg = widgets[TABLE_ID]["config"]
    tcfg["datasources"] = [{
        "type": "entity", "name": None, "entityAliasId": ALIAS_ID,
        "filterId": None,
        "dataKeys": [ts_key(k) for k in
                     ("lat", "lon", "vel", "batt", "conn", "acc",
                      "motionactivities", "tid")],
    }]

    layout = {
        MAP_ID: {"sizeX": 12, "sizeY": 9, "row": 0, "col": 0},
        TRIP_ID: {"sizeX": 12, "sizeY": 9, "row": 0, "col": 12},
        CHART_ID: {"sizeX": 24, "sizeY": 5, "row": 9, "col": 0},
        TABLE_ID: {"sizeX": 24, "sizeY": 6, "row": 14, "col": 0},
    }

    return {
        "title": TITLE,
        "configuration": {
            "description": "Lab 5 §5 — every phone on one OpenStreetMap, plus "
                           "the tracks and the raw latest telemetry.",
            "widgets": widgets,
            "states": {"default": {"name": TITLE, "root": True, "layouts": {
                "main": {"widgets": layout, "gridSettings": {
                    "backgroundColor": "#eeeeee", "columns": 24, "margin": 10,
                    "autoFillHeight": False, "mobileAutoFillHeight": False,
                    "mobileRowHeight": 70, "outerMargin": True,
                    "layoutType": "default"}}}}},
            "entityAliases": {
                ALIAS_ID: {
                    "id": ALIAS_ID, "alias": "Phones",
                    # name-prefix match: no device UUID is baked into the export
                    "filter": {"type": "deviceType", "resolveMultiple": True,
                               "deviceNameFilter": "phone",
                               "deviceTypes": ["default"]}},
                RDV_ALIAS_ID: {
                    "id": RDV_ALIAS_ID, "alias": "Rendezvous",
                    "filter": {"type": "deviceType", "resolveMultiple": False,
                               "deviceNameFilter": "team-rendezvous",
                               "deviceTypes": ["default"]}}},
            # History, not realtime: the trip widget needs a history window
            # (see build_map above), and every timeseries widget now follows
            # this one.  24 h so a full day's capture is visible on open --
            # the phones report a fix every 60 s at rest and every 2-4 s in a
            # car, so a 2 h window silently hides an evening's driving.
            # The "Where the phones are now" map is a *latest* widget and is
            # not bound by this, so live position still streams.
            "timewindow": {"displayValue": "", "selectedTab": 1,
                           "history": {"historyType": 0,
                                       "timewindowMs": 24 * 3600 * 1000},
                           "aggregation": {"type": "NONE", "limit": 50000}},
            "settings": {"stateControllerId": "entity", "showTitle": False,
                         "showDashboardsSelect": True, "showEntitiesSelect": True,
                         "showDashboardTimewindow": True, "showDashboardExport": True,
                         "toolbarAlwaysOpen": True},
        },
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", metavar="FILE",
                    help="also write the dashboard JSON here")
    args = ap.parse_args()

    tb = TB()
    dash = build(tb)
    existing = tb.dashboards().get(TITLE)
    if existing:
        dash["id"] = {"entityType": "DASHBOARD", "id": existing}
        current = tb.get_dashboard(existing)
        dash["createdTime"] = current["createdTime"]
    saved = tb.save_dashboard(dash)
    did = saved["id"]["id"]
    print(f"dashboard {'updated' if existing else 'created'}: {TITLE}")
    print(f"  {os.environ.get('TB_URL', 'http://localhost:8080')}/dashboards/{did}")
    if args.export:
        with open(args.export, "w") as f:
            json.dump({k: v for k, v in saved.items()
                       if k in ("title", "configuration", "name")}, f, indent=1)
        print(f"  exported to {args.export}")


if __name__ == "__main__":
    main()

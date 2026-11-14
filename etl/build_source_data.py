"""Build the source files for the demonstration register from OpenStreetMap and MDB wards.

    python etl/build_source_data.py --osm raw/osm_hatfield.json --wards raw/MDB_Wards_2026.shp

Writes, under data/:
  reference/wards_tsh.geojson         City of Tshwane wards (MDB 2026), study-area wards flagged
  incoming/<source>_<family>.csv      one file per import batch, in the column layout of staging.incoming_assets

Locations from OpenStreetMap are real. Streetlight infill, water mains and hydrants are generated along the real
road network and written to files starting with "synthetic_". Every attribute that OpenStreetMap does not provide
(install dates, lamp types, pipe materials...) is generated with a fixed random seed, so the output is repeatable.
Runs offline; needs geopandas, shapely and pyproj. This step is run once by the maintainer; its outputs are
committed so that the Docker build needs no internet access.
"""
import argparse
import csv
import json
import math
import pathlib

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.ops import linemerge, polygonize, substring, unary_union

ROOT = pathlib.Path(__file__).resolve().parents[1]
STUDY_WARDS = (56, 82, 92)
UTM = "EPSG:32735"          # UTM zone 35S, metres, for lengths, offsets and spacing
AS_OF = 2026
RNG = np.random.default_rng(20261114)

ROAD_CLASS = {"primary": "Primary", "primary_link": "Primary", "secondary": "Secondary", "secondary_link": "Secondary",
              "tertiary": "Tertiary", "tertiary_link": "Tertiary", "unclassified": "Local", "residential": "Residential",
              "living_street": "Living street"}
SURFACE = {"asphalt": "Asphalt", "concrete": "Concrete", "paving_stones": "Paving blocks", "sett": "Paving blocks",
           "unpaved": "Gravel", "gravel": "Gravel", "compacted": "Gravel", "dirt": "Gravel"}
LIGHT_SPACING = {"Primary": 35, "Secondary": 35, "Tertiary": 40, "Local": 45, "Residential": 45, "Living street": 30}
MAIN_DIAMETER = {"Primary": 300, "Secondary": 250, "Tertiary": 160, "Local": 110, "Residential": 110, "Living street": 110}
FIELDS = ["asset_code", "asset_name", "type_code", "status_code", "install_date", "wkt", "lon", "lat", "source_ref", "details"]


# ---------------------------------------------------------------------------------------------- helpers
def rdate(y0, y1):
    y = int(RNG.integers(y0, y1 + 1))
    m = int(RNG.integers(1, 13))
    d = int(RNG.integers(1, 29))
    return f"{y:04d}-{m:02d}-{d:02d}"


def osm_geometry(e):
    if e["type"] == "node":
        return Point(e["lon"], e["lat"])
    if e["type"] == "way":
        pts = [(p["lon"], p["lat"]) for p in e.get("geometry", []) if p]
        if len(pts) < 2:
            return None
        if pts[0] == pts[-1] and len(pts) >= 4 and is_area(e.get("tags", {})):
            return Polygon(pts)
        return LineString(pts)
    if e["type"] == "relation":
        outers = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]]) for m in e.get("members", [])
                  if m["type"] == "way" and m.get("role") == "outer" and len(m.get("geometry", [])) >= 2]
        inners = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]]) for m in e.get("members", [])
                  if m["type"] == "way" and m.get("role") == "inner" and len(m.get("geometry", [])) >= 2]
        polys = list(polygonize(linemerge(outers))) if outers else []
        if not polys:
            return None
        g = unary_union(polys)
        if inners:
            holes = list(polygonize(linemerge(inners)))
            if holes:
                g = g.difference(unary_union(holes))
        return g
    return None


def is_area(tags):
    return any(k in tags for k in ("leisure", "amenity", "man_made", "power", "building", "landuse")) and "highway" not in tags


def split_line(line, max_len=400.0):
    """Split a projected line into near-equal parts no longer than max_len metres."""
    n = max(1, math.ceil(line.length / max_len))
    return [substring(line, line.length * i / n, line.length * (i + 1) / n) for i in range(n)]


def explode_lines(g):
    if g.is_empty:
        return []
    if isinstance(g, LineString):
        return [g]
    if isinstance(g, MultiLineString):
        merged = linemerge(g)
        return list(merged.geoms) if hasattr(merged, "geoms") else [merged]
    if hasattr(g, "geoms"):
        return [x for part in g.geoms for x in explode_lines(part)]
    return []


def write(name, rows):
    out = ROOT / "data" / "incoming" / f"{name}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        for r in rows:
            r = {k: r.get(k, "") for k in FIELDS}
            r["details"] = json.dumps(r["details"] or {}, ensure_ascii=False, separators=(",", ":"))
            w.writerow(r)
    print(f"{name:32s} {len(rows):6d} rows")
    return len(rows)


def wkt(g, nd=7):
    from shapely import wkt as W
    return W.dumps(g, rounding_precision=nd)


# ---------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--osm", required=True)
    ap.add_argument("--wards", required=True)
    a = ap.parse_args()

    # Wards -------------------------------------------------------------------------------------------------
    wards = gpd.read_file(a.wards, where="CAT_B = 'TSH'").to_crs(4326)
    wards = wards[["WardID", "WardNo", "geometry"]].rename(columns={"WardID": "ward_id", "WardNo": "ward_no"})
    wards["in_study_area"] = wards["ward_no"].isin(STUDY_WARDS)
    wards_utm = wards.to_crs(UTM)
    wards_utm["geometry"] = wards_utm.geometry.simplify(5, preserve_topology=True).buffer(0)
    wards_out = wards_utm.to_crs(4326)
    wards_out["geometry"] = wards_out.geometry.set_precision(1e-6)
    p = ROOT / "data" / "reference" / "wards_tsh.geojson"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(wards_out.to_json(drop_id=True), encoding="utf-8")
    print(f"wards: {len(wards_out)} (study area {int(wards_out.in_study_area.sum())})")

    study = unary_union(wards_utm[wards_utm.in_study_area].geometry)
    inner = study.buffer(-2)            # keep generated points clear of the boundary
    to_utm = gpd.GeoSeries([], crs=4326)

    def proj(g):
        return gpd.GeoSeries([g], crs=4326).to_crs(UTM).iloc[0]

    def unproj(g):
        return gpd.GeoSeries([g], crs=UTM).to_crs(4326).iloc[0]

    # OSM ---------------------------------------------------------------------------------------------------
    osm = json.load(open(a.osm, encoding="utf-8"))
    print("OSM snapshot:", osm.get("osm3s", {}).get("timestamp_osm_base"))
    feats = []
    for e in osm["elements"]:
        g = osm_geometry(e)
        if g is not None and not g.is_empty:
            feats.append({"ref": f"{e['type']}/{e['id']}", "tags": e.get("tags", {}), "geometry": g})
    gdf = gpd.GeoDataFrame(feats, crs=4326).to_crs(UTM)
    gdf = gdf[gdf.intersects(study)].copy()
    T = lambda k, v=None: gdf[gdf.tags.map(lambda t: (k in t) if v is None else (t.get(k) in (v if isinstance(v, (set, list, tuple)) else {v})))]

    # Roads -------------------------------------------------------------------------------------------------
    roads = []
    for _, r in T("highway", set(ROAD_CLASS)).iterrows():
        if not isinstance(r.geometry, LineString):
            continue
        cls = ROAD_CLASS[r.tags["highway"]]
        for i, part in enumerate(x for piece in explode_lines(r.geometry.intersection(study)) for x in split_line(piece)):
            if part.length < 10:
                continue
            lanes = int(r.tags.get("lanes", "0").split(";")[0]) if r.tags.get("lanes", "").split(";")[0].isdigit() else \
                {"Primary": 4, "Secondary": 2, "Tertiary": 2}.get(cls, 2)
            lanes = min(max(lanes, 1), 8)
            oneway = r.tags.get("oneway") == "yes"
            if oneway and "lanes" not in r.tags:
                lanes = 2 if cls in ("Primary", "Secondary") else 1
            roads.append({"geom": part, "cls": cls, "name": r.tags.get("name"), "ref": f"{r.ref}#{i + 1}",
                          "surface": SURFACE.get(r.tags.get("surface", ""), "Asphalt"), "lanes": lanes, "oneway": oneway})
    road_rows = []
    for rd in roads:
        built = rdate(1950, 2012) if rd["cls"] in ("Residential", "Local", "Living street") else rdate(1960, 2016)
        width = round(rd["lanes"] * 3.4 + (1.0 if rd["cls"] in ("Primary", "Secondary") else 0.6), 1)
        road_rows.append({"asset_name": rd["name"] or f"Unnamed {rd['cls'].lower()} road", "type_code": "ROAD_SEGMENT", "status_code": "ACTIVE",
                          "install_date": built, "wkt": wkt(unproj(rd["geom"])), "source_ref": rd["ref"],
                          "details": {"road_name": rd["name"], "road_class": rd["cls"], "surface_type": rd["surface"],
                                      "lanes": rd["lanes"], "width_m": width, "is_oneway": rd["oneway"]}})
    write("osm_roads", road_rows)
    road_index = gpd.GeoDataFrame({"name": [r["name"] for r in roads], "cls": [r["cls"] for r in roads]}, geometry=[r["geom"] for r in roads], crs=UTM)

    # Traffic signals: OSM maps one node per approach; cluster nodes within 40 m into one junction ---------------
    sig = T("highway", "traffic_signals")
    sig = sig[sig.geometry.geom_type == "Point"]
    clusters = unary_union(sig.geometry.buffer(20))
    clusters = list(clusters.geoms) if hasattr(clusters, "geoms") else [clusters]
    ts_rows = []
    for c in clusters:
        members = sig[sig.within(c)]
        pt = members.geometry.union_all().centroid
        if not inner.contains(pt):
            continue
        near = road_index[road_index.distance(pt) < 30].dropna(subset=["name"])
        names = list(dict.fromkeys(near.sort_values("cls")["name"]))[:2]
        ts_rows.append({"asset_name": " / ".join(names) if names else "Signalised junction", "type_code": "TRAFFIC_SIGNAL", "status_code": "ACTIVE",
                        "install_date": rdate(1985, 2020), "wkt": wkt(unproj(pt)), "source_ref": sorted(members.ref)[0], "details": {}})
    write("osm_traffic_signals", ts_rows)

    # Streetlights ---------------------------------------------------------------------------------------------
    def light_details(year):
        led = year >= 2016 or RNG.random() < 0.25
        lamp = "LED" if led else ("HPS" if RNG.random() < 0.8 else "MH")
        watt = int(RNG.choice([40, 60, 90, 120])) if led else int(RNG.choice([70, 100, 150, 250]))
        return {"lamp_type": lamp, "wattage_w": watt, "pole_height_m": float(RNG.choice([6.0, 8.0, 9.0, 10.0, 12.0])),
                "pole_material": str(RNG.choice(["Steel", "Steel", "Steel", "Concrete", "Aluminium"]))}

    osm_lights = T("highway", "street_lamp")
    osm_lights = osm_lights[osm_lights.geometry.geom_type == "Point"]
    osm_lights = osm_lights[osm_lights.within(inner)]
    sl_rows = []
    for _, r in osm_lights.iterrows():
        d = rdate(1990, 2024)
        sl_rows.append({"asset_name": None, "type_code": "STREETLIGHT", "status_code": "ACTIVE", "install_date": d,
                        "wkt": wkt(unproj(r.geometry)), "source_ref": r.ref, "details": light_details(int(d[:4]))})
    write("osm_streetlights", sl_rows)

    existing = unary_union(osm_lights.geometry.buffer(15)) if len(osm_lights) else Point(0, 0).buffer(0)
    syn_lights = []
    for rd in roads:
        spacing = LIGHT_SPACING[rd["cls"]]
        offset = 3.0 + rd["lanes"] * 1.7
        both = rd["cls"] in ("Primary", "Secondary")
        line = rd["geom"]
        n = int(line.length // spacing)
        for k in range(n):
            s = spacing / 2 + k * spacing
            if s >= line.length:
                break
            side = (1 if k % 2 == 0 else -1) if both else 1
            p0, p1 = line.interpolate(max(s - 1, 0)), line.interpolate(min(s + 1, line.length))
            dx, dy = p1.x - p0.x, p1.y - p0.y
            norm = math.hypot(dx, dy) or 1
            pt = Point(line.interpolate(s).x - dy / norm * offset * side, line.interpolate(s).y + dx / norm * offset * side)
            if inner.contains(pt) and not existing.contains(pt):
                syn_lights.append(pt)
    # thin points that landed too close to each other at junctions
    kept, grid = [], {}
    for pt in syn_lights:
        key = (int(pt.x // 12), int(pt.y // 12))
        if any(other.distance(pt) < 12 for dx in (-1, 0, 1) for dy in (-1, 0, 1) for other in grid.get((key[0] + dx, key[1] + dy), [])):
            continue
        grid.setdefault(key, []).append(pt)
        kept.append(pt)
    ll = gpd.GeoSeries(kept, crs=UTM).to_crs(4326)
    syn_rows = []
    for i, g in enumerate(ll):
        d = rdate(1985, 2025)
        syn_rows.append({"type_code": "STREETLIGHT", "status_code": "OUT_OF_SERVICE" if RNG.random() < 0.012 else "ACTIVE",
                         "install_date": d, "wkt": wkt(g), "source_ref": f"synthetic/sl/{i + 1}", "details": light_details(int(d[:4]))})
    write("synthetic_streetlights", syn_rows)

    # Water mains and hydrants (synthetic, along roads) -----------------------------------------------------------
    wm_rows, hy_pts, hy_meta = [], [], []
    for i, rd in enumerate(roads):
        main = rd["geom"].offset_curve(2.5)
        if main.is_empty or main.length < 10:
            continue
        main = main.intersection(study.buffer(-1))
        parts = explode_lines(main)
        if not parts:
            continue
        main = max(parts, key=lambda g: g.length)
        if main.length < 10:
            continue
        year = int(RNG.integers(1948, 2021))
        material = (str(RNG.choice(["Asbestos cement", "Cast iron", "Steel"], p=[0.6, 0.3, 0.1])) if year < 1980 else
                    str(RNG.choice(["uPVC", "Asbestos cement", "Steel"], p=[0.6, 0.3, 0.1])) if year < 2000 else
                    str(RNG.choice(["uPVC", "HDPE"], p=[0.65, 0.35])))
        diam = MAIN_DIAMETER[rd["cls"]]
        if material in ("Steel", "Ductile iron") and diam < 150:
            diam = 150
        wm_rows.append({"asset_name": f"{rd['name'] or 'Unnamed road'} main", "type_code": "WATER_MAIN", "status_code": "ACTIVE",
                        "install_date": f"{year}-{int(RNG.integers(1, 13)):02d}-{int(RNG.integers(1, 29)):02d}",
                        "wkt": wkt(unproj(main)), "source_ref": f"synthetic/wm/{i + 1}",
                        "details": {"material": material, "diameter_mm": diam, "pressure_zone": "Hatfield-Brooklyn (illustrative)"}})
        s = 90.0
        while s < main.length:
            hy_pts.append(main.interpolate(s))
            hy_meta.append((year, diam))
            s += 180.0
    write("synthetic_water_mains", wm_rows)
    kept, grid = [], {}
    for pt, meta in zip(hy_pts, hy_meta):
        key = (int(pt.x // 60), int(pt.y // 60))
        if any(o.distance(pt) < 60 for dx in (-1, 0, 1) for dy in (-1, 0, 1) for o, _ in grid.get((key[0] + dx, key[1] + dy), [])) or not inner.contains(pt):
            continue
        grid.setdefault(key, []).append((pt, meta))
        kept.append((pt, meta))
    hy_rows = []
    for i, (pt, (year, diam)) in enumerate(kept):
        hy_rows.append({"type_code": "HYDRANT", "status_code": "ACTIVE", "install_date": f"{max(year, 1960)}-06-01",
                        "wkt": wkt(unproj(pt)), "source_ref": f"synthetic/hy/{i + 1}", "details": {"diameter_mm": 80}})
    write("synthetic_hydrants", hy_rows)

    # Reservoirs (OSM) -------------------------------------------------------------------------------------------
    res = T("man_made", {"reservoir_covered", "water_tower"})
    res = res[res.geometry.geom_type == "Polygon"]
    rs_rows = []
    for _, r in res.iterrows():
        cap = round(r.geometry.area * float(RNG.uniform(4, 7)), -1)
        rs_rows.append({"asset_name": r.tags.get("name") or ("Water tower" if r.tags["man_made"] == "water_tower" else "Covered reservoir"),
                        "type_code": "RESERVOIR", "status_code": "ACTIVE", "install_date": rdate(1955, 2005),
                        "wkt": wkt(unproj(r.geometry)), "source_ref": r.ref,
                        "details": {"material": "Concrete", "capacity_kl": max(cap, 200.0)}})
    write("osm_reservoirs", rs_rows)

    # Stormwater: channels from OSM waterways, culverts where they cross roads ------------------------------------
    ww = T("waterway", {"stream", "drain", "canal", "ditch"})
    ww = ww[ww.geometry.geom_type == "LineString"]
    sc_rows, cv_rows, seen = [], [], []
    for _, r in ww.iterrows():
        kind = r.tags["waterway"]
        for i, part in enumerate(x for piece in explode_lines(r.geometry.intersection(study)) for x in split_line(piece, 500)):
            if part.length < 15:
                continue
            sc_rows.append({"asset_name": r.tags.get("name") or ("Stormwater drain" if kind in ("drain", "ditch") else "Watercourse channel"),
                            "type_code": "CHANNEL", "status_code": "ACTIVE", "install_date": rdate(1950, 1995),
                            "wkt": wkt(unproj(part)), "source_ref": f"{r.ref}#{i + 1}",
                            "details": {"structure": "Channel", "is_lined": kind in ("drain", "canal") or RNG.random() < 0.4}})
        for _, rd in road_index[road_index.intersects(r.geometry)].iterrows():
            x = r.geometry.intersection(rd.geometry)
            for pt in (list(x.geoms) if hasattr(x, "geoms") else [x]):
                if pt.geom_type != "Point" or not inner.contains(pt) or any(pt.distance(s) < 25 for s in seen):
                    continue
                seen.append(pt)
                cv_rows.append({"asset_name": f"{r.tags.get('name') or 'Watercourse'} under {rd['name'] or 'road'}",
                                "type_code": "CULVERT", "status_code": "ACTIVE", "install_date": rdate(1950, 2000),
                                "wkt": wkt(unproj(pt)), "source_ref": f"derived/{r.ref}/{len(seen)}",
                                "details": {"structure": "Culvert", "size_mm": int(RNG.choice([600, 900, 1200, 1500, 2400])), "is_lined": True}})
    write("osm_stormwater_channels", sc_rows)
    write("osm_culverts", cv_rows)

    # Electricity (OSM) ------------------------------------------------------------------------------------------
    def kv(tags, default):
        v = tags.get("voltage", "").split(";")[0]
        return round(int(v) / 1000, 2) if v.isdigit() and int(v) > 0 else default

    el_rows = []
    for _, r in T("power", "substation").iterrows():
        g = r.geometry if r.geometry.geom_type == "Polygon" else None
        if g is None or not inner.contains(g.representative_point()):
            continue
        el_rows.append({"asset_name": r.tags.get("name") or "Substation", "type_code": "SUBSTATION", "status_code": "ACTIVE",
                        "install_date": rdate(1960, 2010), "wkt": wkt(unproj(g)), "source_ref": r.ref,
                        "details": {"voltage_kv": kv(r.tags, 11.0), "rating_kva": int(RNG.choice([5000, 10000, 20000, 40000]))}})
    for _, r in T("power", {"line", "minor_line"}).iterrows():
        if r.geometry.geom_type != "LineString":
            continue
        for i, part in enumerate(x for piece in explode_lines(r.geometry.intersection(study)) for x in split_line(piece, 800)):
            if part.length < 20:
                continue
            el_rows.append({"asset_name": r.tags.get("name") or f"{kv(r.tags, 11.0):g} kV line", "type_code": "POWER_LINE", "status_code": "ACTIVE",
                            "install_date": rdate(1965, 2005), "wkt": wkt(unproj(part)), "source_ref": f"{r.ref}#{i + 1}",
                            "details": {"voltage_kv": kv(r.tags, 11.0)}})
    write("osm_electricity", el_rows)

    # Community facilities (OSM) ---------------------------------------------------------------------------------
    fac_rows = []
    def add_fac(sel, type_code, use, polygon=False, min_area=0):
        for _, r in sel.iterrows():
            g = r.geometry
            if polygon:
                if g.geom_type not in ("Polygon", "MultiPolygon"):
                    continue
                g = g.intersection(study)
                if g.is_empty or g.area < min_area:
                    continue
                if g.geom_type == "MultiPolygon":
                    g = max(g.geoms, key=lambda x: x.area)
            else:
                g = g.representative_point() if g.geom_type != "Point" else g
                if not inner.contains(g):
                    continue
            fac_rows.append({"asset_name": r.tags.get("name") or use, "type_code": type_code, "status_code": "ACTIVE",
                             "install_date": rdate(1960, 2018), "wkt": wkt(unproj(g)), "source_ref": r.ref,
                             "details": {"facility_use": use, "operator": "Assumed municipal (not verified)",
                                         "is_accessible": r.tags.get("wheelchair") == "yes" or RNG.random() < 0.4}})
    add_fac(T("leisure", "park"), "PARK", "Park", polygon=True, min_area=300)
    add_fac(T("leisure", "playground"), "PLAYGROUND", "Playground")
    add_fac(T("leisure", {"sports_centre", "stadium"}), "SPORTS_FACILITY", "Sports facility")
    add_fac(T("amenity", "library"), "LIBRARY", "Library")
    add_fac(T("amenity", "clinic"), "CLINIC", "Clinic")
    add_fac(T("amenity", "community_centre"), "COMMUNITY_CENTRE", "Community centre")
    add_fac(T("amenity", "toilets"), "PUBLIC_TOILET", "Public toilet")
    write("osm_facilities", fac_rows)

    rc_rows = []
    for _, r in T("amenity", "recycling").iterrows():
        g = r.geometry if r.geometry.geom_type == "Point" else r.geometry.representative_point()
        if inner.contains(g):
            rc_rows.append({"asset_name": r.tags.get("name") or "Recycling drop-off", "type_code": "RECYCLING_POINT", "status_code": "ACTIVE",
                            "install_date": rdate(2008, 2022), "wkt": wkt(unproj(g)), "source_ref": r.ref, "details": {}})
    write("osm_recycling", rc_rows)

    meta = {"osm_timestamp": osm.get("osm3s", {}).get("timestamp_osm_base"), "study_wards": STUDY_WARDS,
            "study_area_km2": round(study.area / 1e6, 2), "seed": 20261114}
    (ROOT / "data" / "source_metadata.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(meta)


if __name__ == "__main__":
    main()

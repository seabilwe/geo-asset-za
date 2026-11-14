"""Read-only queries behind the public API and the static snapshot. All of them read the api schema only.

Every function takes an open connection (the public application role in production) and returns plain Python
structures ready for JSON. The static export (web/export_snapshot.py) calls the same functions, so the
published snapshot and the live API cannot disagree.
"""
import json

CLASSES = ("ROADS", "LIGHT", "WATER", "STORM", "ELEC", "FAC", "WASTE")


def _rows(cur):
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def kpis(conn):
    return _rows(conn.execute("SELECT * FROM api.kpis"))[0]


def summary_by_type(conn):
    return _rows(conn.execute("SELECT * FROM api.summary_by_type ORDER BY class_code, assets DESC"))


def spend_by_month(conn):
    return _rows(conn.execute("SELECT month, class_code, cost_status, amount_zar FROM api.spend_by_month ORDER BY month, class_code, cost_status"))


def priorities(conn, limit=25):
    return _rows(conn.execute("SELECT * FROM api.priority_assets LIMIT %s", (min(int(limit), 200),)))


def work_order_performance(conn):
    return _rows(conn.execute("SELECT * FROM api.work_order_performance ORDER BY class_name, response_days"))


def lookups(conn):
    out = {}
    for lookup, code, label, extra in conn.execute("SELECT lookup, code, label, extra FROM api.lookups ORDER BY lookup, code"):
        out.setdefault(lookup, []).append({"code": code, "label": label, "extra": extra})
    return out


def wards(conn):
    feats = [{"type": "Feature", "properties": {"ward_no": n, "ward_id": i}, "geometry": json.loads(g)}
             for n, i, g in conn.execute("SELECT ward_no, ward_id, ST_AsGeoJSON(geom, 6) FROM api.wards ORDER BY ward_no")]
    return {"type": "FeatureCollection", "features": feats}


# short property key -> column expression in api.assets
ASSET_PROPS = [("c", "asset_code"), ("n", "coalesce(asset_name, '')"), ("t", "type_code"), ("g", "condition_grade"), ("w", "ward_no"),
               ("y", "install_year"), ("o", "CASE WHEN inspection_overdue THEN 1 ELSE 0 END"), ("s", "location_source")]


def assets_geojson(conn, class_code=None, type_code=None, ward=None, condition=None, bbox=None, limit=None, precision=6):
    """Assets as compact GeoJSON. Property keys are one letter to keep the snapshot small:
    c code, n name, t type, g latest condition grade, w ward, y install year, o inspection overdue, s location source."""
    where, params = ["true"], []
    if class_code:
        where.append("class_code = %s"); params.append(class_code)
    if type_code:
        where.append("type_code = %s"); params.append(type_code)
    if ward:
        where.append("ward_no = %s"); params.append(int(ward))
    if condition:
        where.append("condition_grade = %s"); params.append(int(condition))
    if bbox:
        x0, y0, x1, y1 = (float(v) for v in bbox)
        where.append("geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)"); params += [x0, y0, x1, y1]
    sql = f"""SELECT json_build_object('type', 'FeatureCollection', 'features', coalesce(json_agg(json_build_object(
                  'type', 'Feature', 'properties', json_build_object({', '.join(f"'{k}', {expr}" for k, expr in ASSET_PROPS)}),
                  'geometry', ST_AsGeoJSON(geom, {int(precision)})::json) ORDER BY asset_code), '[]'::json))
                FROM (SELECT * FROM api.assets WHERE {' AND '.join(where)} ORDER BY asset_code {'LIMIT %s' if limit else ''}) a"""
    if limit:
        params.append(min(int(limit), 20000))
    return conn.execute(sql, params).fetchone()[0]


def asset(conn, code):
    row = _rows(conn.execute("""SELECT asset_code, asset_name, class_name, type_name, ward_no, status, install_year, age_years,
                                       condition_grade, condition_label, last_inspected_on, inspection_overdue, quantity, cost_unit,
                                       replacement_value_zar, location_source, attributes_synthetic
                                  FROM api.assets WHERE asset_code = %s""", (code,)))
    if not row:
        return None
    out = row[0]
    d = conn.execute("SELECT streetlight, road, water, electrical, stormwater, facility FROM api.asset_details WHERE asset_code = %s", (code,)).fetchone()
    out["details"] = next((x for x in d if x), {}) if d else {}
    out["history"] = history(conn, code)
    return out


def history(conn, code, limit=12):
    return _rows(conn.execute("""SELECT event, event_date, summary, detail, status, actual_cost_zar FROM api.asset_history
                                  WHERE asset_code = %s ORDER BY event_date DESC, event LIMIT %s""", (code, limit)))

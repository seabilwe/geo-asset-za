"""Export a static snapshot of the public views for the portfolio page (which has no database behind it).

    python web/export_snapshot.py [--out web/data]

Uses the same query functions as the API (api/queries.py), connected as the public application role, so the
snapshot contains exactly what the API would serve. The evidence file (health, backups, migrations, benchmark)
is read as the monitoring role. Files:

  meta.json  kpis.json  summary.json  condition.json  spend.json  priorities.json  performance.json  lookups.json  wards.geojson
  assets_<CLASS>.geojson    one per asset class, loaded on demand by the map
  details_<CLASS>.json      attributes and recent history per asset, loaded when an asset is clicked
  evidence.json             database administration evidence for the page
"""
import argparse
import datetime as dt
import decimal
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from api import queries as q  # noqa: E402
from gaz.db import connect  # noqa: E402


def clean(v):
    if isinstance(v, decimal.Decimal):
        f = float(v)
        return int(f) if f.is_integer() else round(f, 2)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    return v


def dump(path, obj):
    path.write_text(json.dumps(clean(obj), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path.stat().st_size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "web" / "data")
    a = ap.parse_args()
    out = a.out
    out.mkdir(parents=True, exist_ok=True)
    pw = os.environ.get("GAZ_PASSWORD_WEB_APP") or os.environ.get("GAZ_DEMO_PASSWORD")
    sizes = {}
    with connect(user=os.environ.get("GAZ_WEB_USER", "web_app"), password=pw, app="export_snapshot") as conn:
        k = q.kpis(conn)
        sizes["kpis.json"] = dump(out / "kpis.json", k)
        sizes["summary.json"] = dump(out / "summary.json", q.summary_by_type(conn))
        sizes["condition.json"] = dump(out / "condition.json", q.condition_by_type(conn))
        sizes["spend.json"] = dump(out / "spend.json", q.spend_by_month(conn))
        sizes["priorities.json"] = dump(out / "priorities.json", q.priorities(conn, 25))
        sizes["performance.json"] = dump(out / "performance.json", q.work_order_performance(conn))
        sizes["lookups.json"] = dump(out / "lookups.json", q.lookups(conn))
        sizes["wards.geojson"] = dump(out / "wards.geojson", q.wards(conn))
        for cls in q.CLASSES:
            fc = q.assets_geojson(conn, class_code=cls, precision=6)
            sizes[f"assets_{cls}.geojson"] = dump(out / f"assets_{cls}.geojson", fc)
            details = {}
            codes = [f["properties"]["c"] for f in fc["features"]]
            # one query per class, not per asset
            for code, row in conn.execute("""SELECT d.asset_code, to_jsonb(d) - 'asset_code' FROM api.asset_details d
                                              JOIN api.assets a USING (asset_code) WHERE a.class_code = %s""", (cls,)):
                det = next((v for v in row.values() if v), {})
                details[code] = {"d": {kk: vv for kk, vv in det.items() if vv is not None}, "h": []}
            for code, event, day, summary, detail, status, cost in conn.execute(
                    """SELECT h.asset_code, h.event, h.event_date, h.summary, h.detail, h.status, h.actual_cost_zar
                         FROM (SELECT h.*, row_number() OVER (PARTITION BY h.asset_code ORDER BY h.event_date DESC, h.event) rn
                                 FROM api.asset_history h JOIN api.assets a USING (asset_code) WHERE a.class_code = %s) h
                        WHERE rn <= 6 ORDER BY h.asset_code, h.event_date DESC""", (cls,)):
                details.setdefault(code, {"d": {}, "h": []})["h"].append([event[0], day, summary, detail, status, cost])
            missing = set(codes) - set(details)
            assert not missing, f"details missing for {len(missing)} assets"
            sizes[f"details_{cls}.json"] = dump(out / f"details_{cls}.json", details)

    mpw = os.environ.get("GAZ_PASSWORD_MONITOR") or os.environ.get("GAZ_DEMO_PASSWORD")
    with connect(user=os.environ.get("GAZ_MONITOR_USER", "monitor"), password=mpw, app="export_snapshot") as conn:
        health = [dict(zip(("metric", "value", "status", "threshold"), r)) for r in conn.execute("SELECT * FROM admin.v_health")]
        backups = [dict(zip(("kind", "finished_at", "status", "size_bytes", "details"), r)) for r in
                   conn.execute("SELECT kind, finished_at, status, size_bytes, details FROM admin.backup_log ORDER BY backup_id DESC LIMIT 4")]
        tables = [dict(zip(("table", "rows", "size"), r)) for r in
                  conn.execute("SELECT schema_name || '.' || table_name, approx_rows, total_size FROM admin.v_table_sizes LIMIT 10")]
        rejections = [dict(zip(("file", "rule", "description", "rows"), r)) for r in
                      conn.execute("SELECT source_file, rule_code, description, rows_failed FROM admin.v_failed_imports")]
        size = conn.execute("SELECT size FROM admin.v_database_size").fetchone()[0]
    with connect(app="export_snapshot") as conn:     # owner: migration list and import totals
        migrations = [dict(zip(("version", "name", "applied_at"), r)) for r in
                      conn.execute("SELECT version, name, applied_at FROM admin.schema_migrations ORDER BY version")]
        imports = dict(zip(("batches", "rows", "promoted", "rejected"),
                           conn.execute("SELECT count(*), sum(rows_total), sum(rows_promoted), sum(rows_rejected) FROM staging.import_batches").fetchone()))
        counts = dict(conn.execute("""SELECT 'inspections', count(*) FROM maintenance.inspections UNION ALL
                                      SELECT 'work_orders', count(*) FROM maintenance.work_orders UNION ALL
                                      SELECT 'activities', count(*) FROM maintenance.maintenance_activities UNION ALL
                                      SELECT 'cost_lines', count(*) FROM maintenance.maintenance_costs UNION ALL
                                      SELECT 'audit_rows', count(*) FROM audit.change_log""").fetchall())
    restore = next((b for b in backups if b["kind"] == "RESTORE_TEST"), None)
    bench_path = ROOT / "administration" / "performance" / "results" / "benchmark.json"
    bench = json.loads(bench_path.read_text()) if bench_path.exists() else None
    evidence = {"database_size": size, "health": health, "restore_test": restore, "largest_tables": tables, "import_rejections": rejections,
                "migrations": migrations, "imports": imports, "counts": counts,
                "benchmark": {"points": bench["points"], "server": bench["server"],
                              "spatial": {kk: {s: {"median_ms": v[s]["median_ms"], "scans": v[s]["scans"], "rows": v[s]["rows"],
                                                   "pages": v[s]["shared_hit"] + v[s]["shared_read"]} for s in ("before", "after", "clustered")}
                                          for kk, v in bench["spatial"].items()},
                              "register": {s: bench["register"][s]["median_ms"] for s in ("before", "after")}} if bench else None}
    sizes["evidence.json"] = dump(out / "evidence.json", evidence)
    src = json.loads((ROOT / "data" / "source_metadata.json").read_text())
    sizes["meta.json"] = dump(out / "meta.json", {"exported_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                                                 "data_as_of": k["data_as_of"], "osm_snapshot": src["osm_timestamp"],
                                                 "study_wards": src["study_wards"], "study_area_km2": src["study_area_km2"]})
    total = sum(sizes.values())
    for name, s in sorted(sizes.items()):
        print(f"{name:28s} {s / 1024:8.1f} KB")
    print(f"{'total':28s} {total / 1024:8.1f} KB")


if __name__ == "__main__":
    main()

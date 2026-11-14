"""Print the database health check and save a snapshot.

    python administration/monitoring/health_report.py [--json out.json]

Connects as the monitoring login role (GAZ_MONITOR_USER, default monitor), which can read the admin views and
PostgreSQL's statistics but no asset data. Exits with status 1 if any metric is FAIL and 2 on WARN only, so a
scheduler or CI step can alert on it.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gaz.db import connect, login_password  # noqa: E402


def collect():
    user = os.environ.get("GAZ_MONITOR_USER", "monitor")
    pw = login_password(user)
    with connect(user=user, password=pw, app="health_report") as conn:
        health = [dict(zip(("metric", "value", "status", "threshold"), r)) for r in conn.execute("SELECT * FROM admin.v_health")]
        tables = [dict(zip(("schema", "table", "rows", "size", "index_size"), r)) for r in
                  conn.execute("SELECT schema_name, table_name, approx_rows, total_size, index_size FROM admin.v_table_sizes LIMIT 12")]
        connections = [dict(zip(("role", "state", "connections"), r)) for r in
                       conn.execute("SELECT role_name, state, connections FROM admin.v_connections ORDER BY connections DESC")]
        unused = [dict(zip(("table", "index", "size"), r)) for r in
                  conn.execute("SELECT schema_name || '.' || table_name, index_name, index_size FROM admin.v_index_usage WHERE unused_candidate LIMIT 10")]
        dead = [dict(zip(("table", "live", "dead", "dead_pct", "last_autovacuum"), (r[0], r[1], r[2], float(r[3] or 0), r[4].isoformat() if r[4] else None)))
                for r in conn.execute("SELECT schema_name || '.' || table_name, live_rows, dead_rows, dead_pct, last_autovacuum FROM admin.v_dead_tuples LIMIT 6")]
        backups = [dict(zip(("kind", "finished_at", "status", "size_bytes"), (r[0], r[1].isoformat() if r[1] else None, r[2], r[3]))) for r in
                   conn.execute("SELECT kind, finished_at, status, size_bytes FROM admin.backup_log ORDER BY backup_id DESC LIMIT 6")]
        imports = [dict(zip(("batch", "file", "rule", "description", "rows"), r)) for r in
                   conn.execute("SELECT batch_id, source_file, rule_code, description, rows_failed FROM admin.v_failed_imports LIMIT 10")]
    return {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "health": health, "largest_tables": tables,
            "connections": connections, "unused_indexes": unused, "dead_tuples": dead, "recent_backups": backups, "import_rejections": imports}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=pathlib.Path, help="also write the snapshot to this file")
    a = ap.parse_args()
    snap = collect()
    w = max(len(h["metric"]) for h in snap["health"])
    for h in snap["health"]:
        print(f"{h['status']:4s}  {h['metric']:{w}s}  {h['value']:>20s}   ({h['threshold']})")
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(snap, indent=1, default=str), encoding="utf-8")
    statuses = {h["status"] for h in snap["health"]}
    sys.exit(1 if "FAIL" in statuses else (2 if "WARN" in statuses else 0))


if __name__ == "__main__":
    main()

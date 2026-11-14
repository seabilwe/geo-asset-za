"""Prove that the latest backup can be restored: restore it into a scratch database and check it.

    python administration/restore/restore_test.py [--file backups/geoasset_za_....dump] [--keep-db]

Checks, each recorded as pass or fail:
  1. the file's SHA-256 matches the checksum logged at backup time (the file is the one that was written)
  2. pg_restore completes without errors into a new database with PostGIS available
  3. every table has exactly the row count logged at backup time
  4. the restored database has the same number of tables, views, functions, triggers, indexes and RLS policies
  5. the schema version (latest migration) matches
  6. spatial data works: geometries are valid and the GiST index is used by a bounding-box query
  7. the API headline figures (api.kpis) match the source database
The result goes to admin.backup_log (kind RESTORE_TEST) in the source database and to a Markdown report in
administration/restore/reports/. The scratch database is dropped afterwards unless --keep-db is given.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from psycopg import sql  # noqa: E402
from gaz.db import connect, DEFAULT_DB  # noqa: E402

OBJECTS = """
SELECT (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = ANY(%(s)s) AND c.relkind = 'r') AS tables,
       (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = ANY(%(s)s) AND c.relkind IN ('v', 'm')) AS views,
       (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = ANY(%(s)s)) AS functions,
       (SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = ANY(%(s)s) AND NOT t.tgisinternal) AS triggers,
       (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = ANY(%(s)s) AND c.relkind = 'i') AS indexes,
       (SELECT count(*) FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = ANY(%(s)s)) AS policies"""
SCHEMAS = ["reference", "assets", "maintenance", "operations", "audit", "staging", "api", "admin"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=pathlib.Path)
    ap.add_argument("--keep-db", action="store_true")
    a = ap.parse_args()
    src_db = os.environ.get("PGDATABASE", DEFAULT_DB)
    target = f"{src_db}_restore_test"
    started = dt.datetime.now(dt.timezone.utc)
    checks = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "result": "pass" if ok else "FAIL", "detail": detail})
        print(f"[{'pass' if ok else 'FAIL'}] {name}  {detail}")

    with connect(autocommit=True, app="restore_test") as src:
        q = "SELECT backup_id, file_name, sha256, details FROM admin.backup_log WHERE kind = 'BACKUP' AND status = 'SUCCESS'"
        row = (src.execute(q + " AND file_name = %s ORDER BY backup_id DESC LIMIT 1", (a.file.name,)).fetchone() if a.file
               else src.execute(q + " ORDER BY backup_id DESC LIMIT 1").fetchone())
        if not row:
            sys.exit("No successful backup is logged. Run administration/backup/backup.py first.")
        backup_id, file_name, logged_sha, details = row
        path = a.file or (ROOT / "backups" / file_name)
        log_id = src.execute("INSERT INTO admin.backup_log (kind, started_at, status, file_name) VALUES ('RESTORE_TEST', now(), 'RUNNING', %s) RETURNING backup_id",
                             (file_name,)).fetchone()[0]
        src_objects = src.execute(OBJECTS, {"s": SCHEMAS}).fetchone()
        src_kpis = src.execute("SELECT total_assets, open_work_orders, replacement_value_zar FROM api.kpis").fetchone()

    t0 = time.perf_counter()
    ok_all = False
    try:
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        check("Checksum matches backup log", h == logged_sha, f"sha256 {h[:16]}…")

        with connect(dbname="postgres", autocommit=True, app="restore_test") as adm:
            adm.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(target)))
            adm.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
        r = subprocess.run(["pg_restore", "--exit-on-error", "--dbname", target, str(path)], capture_output=True, text=True)
        check("pg_restore completed without errors", r.returncode == 0, (r.stderr.strip()[:300] or f"{time.perf_counter() - t0:.1f} s"))

        with connect(dbname=target, autocommit=True, app="restore_test") as dst:
            expected = details["row_counts"]
            mismatches = []
            for table, n in expected.items():
                got = dst.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                # the backup log itself gains rows between the count and the dump
                if got != n and table != "admin.backup_log":
                    mismatches.append(f"{table}: expected {n}, got {got}")
            check("Row counts match for every table", not mismatches,
                  f"{len(expected)} tables, {sum(v for k, v in expected.items() if k != 'admin.backup_log'):,} rows" if not mismatches else "; ".join(mismatches[:5]))

            dst_objects = dst.execute(OBJECTS, {"s": SCHEMAS}).fetchone()
            check("Same number of database objects", tuple(dst_objects) == tuple(src_objects),
                  "tables {}, views {}, functions {}, triggers {}, indexes {}, policies {}".format(*dst_objects))

            v = dst.execute("SELECT max(version) FROM admin.schema_migrations").fetchone()[0]
            check("Schema version matches", v == details["schema_version"], v)

            postgis = dst.execute("SELECT postgis_lib_version()").fetchone()[0]
            invalid = dst.execute("SELECT count(*) FROM assets.infrastructure_assets WHERE NOT ST_IsValid(geom)").fetchone()[0]
            dst.execute("SET enable_seqscan = off")
            plan = json.dumps(dst.execute("""EXPLAIN (FORMAT JSON) SELECT count(*) FROM assets.infrastructure_assets
                                             WHERE geom && ST_MakeEnvelope(28.22, -25.76, 28.24, -25.74, 4326)""").fetchone()[0])
            check("Spatial data valid and GiST index used", invalid == 0 and "infrastructure_assets_geom_gist" in plan,
                  f"PostGIS {postgis}, {invalid} invalid geometries")

            dst.execute("REFRESH MATERIALIZED VIEW operations.asset_condition_summary")
            kp = dst.execute("SELECT total_assets, open_work_orders, replacement_value_zar FROM api.kpis").fetchone()
            check("API headline figures match", tuple(kp) == tuple(src_kpis), f"{kp[0]:,} assets, {kp[1]} open work orders")
        ok_all = all(c["result"] == "pass" for c in checks)
    except Exception as e:
        check("Restore test ran to completion", False, str(e)[:300])
    finally:
        if not a.keep_db:
            with connect(dbname="postgres", autocommit=True, app="restore_test") as adm:
                adm.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(target)))

    seconds = round(time.perf_counter() - t0, 1)
    with connect(autocommit=True, app="restore_test") as src:
        src.execute("UPDATE admin.backup_log SET finished_at = now(), status = %s, details = %s WHERE backup_id = %s",
                    ("SUCCESS" if ok_all else "FAILED", json.dumps({"backup_id": backup_id, "seconds": seconds, "checks": checks}), log_id))

    reports = pathlib.Path(__file__).parent / "reports"
    reports.mkdir(exist_ok=True)
    md = [f"# Restore test {started:%Y-%m-%d %H:%M} UTC", "",
          f"- Backup file: `{file_name}` (backup log id {backup_id})", f"- Restored into: `{target}` (dropped afterwards: {not a.keep_db})",
          f"- Duration: {seconds} s", f"- Result: **{'PASSED' if ok_all else 'FAILED'}**", "",
          "| Check | Result | Detail |", "|---|---|---|"] + [f"| {c['check']} | {c['result']} | {c['detail']} |" for c in checks]
    (reports / "latest.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nRestore test {'PASSED' if ok_all else 'FAILED'} in {seconds} s")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()

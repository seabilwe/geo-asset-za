"""Build the GEO-ASSET ZA database from nothing, or bring an existing one up to date.

    python etl/bootstrap.py            create if missing, migrate, load anything not yet loaded
    python etl/bootstrap.py --reset    drop the database and build it again

Steps: create database -> apply migrations -> reference data and wards -> login roles ->
import every file in data/incoming through staging -> synthetic maintenance history -> refresh reporting.
Every step skips itself when its work is already done, so the Docker service can run this on each start.
Connects as a superuser (PGUSER), except for the imports, which run as the ETL login role.
"""
import argparse
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from psycopg import sql  # noqa: E402
from gaz.db import connect, DEFAULT_DB  # noqa: E402


def step(title, *cmd):
    t0 = time.perf_counter()
    print(f"\n== {title}")
    subprocess.run([sys.executable, *cmd], cwd=ROOT, check=True)
    print(f"   done in {time.perf_counter() - t0:.1f} s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="drop and rebuild the database")
    a = ap.parse_args()
    db = os.environ.get("PGDATABASE", DEFAULT_DB)

    with connect(dbname="postgres", autocommit=True, app="bootstrap") as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,)).fetchone()
        if exists and a.reset:
            conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (db,))
            conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(db)))
            exists = None
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8'").format(sql.Identifier(db)))
            print(f"created database {db}")

    step("Migrations", "database/migrate.py")
    step("Reference data and wards", "etl/load_reference.py")
    step("Login roles", "administration/security/create_login_roles.py")

    with connect(app="bootstrap") as conn:
        n_assets = conn.execute("SELECT count(*) FROM assets.infrastructure_assets").fetchone()[0]
    if n_assets == 0:
        files = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "data" / "incoming").glob("*.csv") if not p.name.startswith("sample_"))
        step("Import assets through staging", "etl/import_assets.py", *files)
    else:
        print(f"\n== Import assets: register already holds {n_assets:,} assets, skipped")

    step("Synthetic maintenance history", "etl/generate_history.py")

    with connect(autocommit=True, app="bootstrap") as conn:
        conn.execute("SELECT operations.refresh_reporting()")
        conn.execute("ANALYZE")
        k = conn.execute("SELECT total_assets, open_work_orders FROM api.kpis").fetchone()
    print(f"\nReady: {k[0]:,} assets, {k[1]:,} open work orders.")


if __name__ == "__main__":
    main()

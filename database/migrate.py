"""Apply the versioned SQL migrations in database/migrations, in order, exactly once each.

    python database/migrate.py            apply pending migrations
    python database/migrate.py --status   list applied and pending migrations

Each migration runs in its own transaction and is recorded in admin.schema_migrations with a SHA-256 checksum.
If a file that has already been applied is edited, the runner stops: applied migrations are never changed,
a new migration is added instead. Must run as a superuser (PostGIS needs one to install).
"""
import argparse
import hashlib
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from gaz.db import connect  # noqa: E402

MIGRATIONS = pathlib.Path(__file__).parent / "migrations"

BOOTSTRAP = """
CREATE SCHEMA IF NOT EXISTS admin;
CREATE TABLE IF NOT EXISTS admin.schema_migrations (
    version     varchar(10)  PRIMARY KEY,
    name        varchar(200) NOT NULL,
    checksum    char(64)     NOT NULL,
    applied_at  timestamptz  NOT NULL DEFAULT now(),
    applied_by  name         NOT NULL DEFAULT current_user,
    duration_ms integer      NOT NULL
);
COMMENT ON TABLE admin.schema_migrations IS 'Migrations applied to this database, with the checksum of each file at the time.';
"""


def files():
    for p in sorted(MIGRATIONS.glob("V*__*.sql")):
        version, name = p.stem.split("__", 1)
        yield version, name, p, hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    with connect(app="migrate") as conn:
        conn.execute(BOOTSTRAP)
        conn.commit()
        applied = {v: c for v, c in conn.execute("SELECT version, checksum FROM admin.schema_migrations")}
        pending = []
        for version, name, path, checksum in files():
            if version in applied:
                if applied[version] != checksum:
                    sys.exit(f"{path.name} was changed after it was applied. Add a new migration instead.")
                if args.status:
                    print(f"applied  {version} {name}")
            else:
                pending.append((version, name, path, checksum))
                if args.status:
                    print(f"pending  {version} {name}")
        if args.status:
            return
        for version, name, path, checksum in pending:
            t0 = time.perf_counter()
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO admin.schema_migrations (version, name, checksum, duration_ms) VALUES (%s, %s, %s, %s)",
                             (version, name, checksum, int((time.perf_counter() - t0) * 1000)))
            print(f"applied  {version} {name}  ({(time.perf_counter() - t0) * 1000:.0f} ms)")
        # hand any new objects to gaz_owner (V013 defines the function; skip on a database older than that)
        if conn.execute("SELECT to_regprocedure('admin.apply_ownership()') IS NOT NULL").fetchone()[0]:
            conn.execute("SELECT admin.apply_ownership()")
            conn.commit()
        if not pending:
            print("Database is up to date.")


if __name__ == "__main__":
    main()

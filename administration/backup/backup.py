"""Back up the GEO-ASSET ZA database.

    python administration/backup/backup.py [--dir backups] [--keep 7]

Writes two files per run:
  geoasset_za_<timestamp>.dump        pg_dump custom format (compressed, restorable table by table with pg_restore)
  globals_<timestamp>.sql             roles and memberships (pg_dumpall --globals-only, without passwords)
Roles live in the cluster, not in the database, so a database dump alone cannot recreate them.

Each run is logged in admin.backup_log with the file size, SHA-256 checksum and the row count of every table at
the time of the dump; the restore test compares against those counts. Old dumps beyond --keep are deleted.
This is a logical backup: it captures one consistent moment. Recovery to any point in time would need physical
backups with WAL archiving (pg_basebackup or a tool such as pgBackRest); see documentation/recovery_procedures.md.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gaz.db import connect, DEFAULT_DB  # noqa: E402

COUNT_SQL = """
SELECT n.nspname || '.' || c.relname
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE c.relkind = 'r' AND n.nspname IN ('reference', 'assets', 'maintenance', 'audit', 'staging', 'admin')
 ORDER BY 1"""


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_backup(out_dir: pathlib.Path, keep: int = 7) -> dict:
    db = os.environ.get("PGDATABASE", DEFAULT_DB)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    dump = out_dir / f"{db}_{stamp}.dump"
    globals_file = out_dir / f"globals_{stamp}.sql"
    with connect(autocommit=True, app="backup") as conn:
        bid = conn.execute("INSERT INTO admin.backup_log (kind, started_at, status, file_name) VALUES ('BACKUP', now(), 'RUNNING', %s) RETURNING backup_id",
                           (dump.name,)).fetchone()[0]
        try:
            # counts taken in a REPEATABLE READ snapshot, as close as possible to the dump's own snapshot
            with conn.transaction():
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                counts = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for (t,) in conn.execute(COUNT_SQL).fetchall()}
                version = conn.execute("SELECT max(version) FROM admin.schema_migrations").fetchone()[0]
            subprocess.run(["pg_dump", "--format=custom", "--compress=6", "--file", str(dump), db], check=True)
            subprocess.run(["pg_dumpall", "--globals-only", "--no-role-passwords", "--file", str(globals_file)], check=True)
            info = {"database": db, "schema_version": version, "row_counts": counts, "globals_file": globals_file.name,
                    "pg_dump": subprocess.run(["pg_dump", "--version"], capture_output=True, text=True).stdout.strip()}
            size, digest = dump.stat().st_size, sha256(dump)
            conn.execute("UPDATE admin.backup_log SET finished_at = now(), status = 'SUCCESS', size_bytes = %s, sha256 = %s, details = %s WHERE backup_id = %s",
                         (size, digest, json.dumps(info), bid))
        except Exception as e:
            conn.execute("UPDATE admin.backup_log SET finished_at = now(), status = 'FAILED', details = %s WHERE backup_id = %s",
                         (json.dumps({"error": str(e)}), bid))
            raise
    # retention: keep the newest `keep` dumps (and their globals files)
    dumps = sorted(out_dir.glob(f"{db}_*.dump"))
    for old in dumps[:-keep]:
        old.unlink()
        g = out_dir / old.name.replace(f"{db}_", "globals_").replace(".dump", ".sql")
        g.unlink(missing_ok=True)
    result = {"backup_id": bid, "file": str(dump), "size_bytes": size, "sha256": digest, "tables": len(counts), "rows": sum(counts.values())}
    print(json.dumps(result, indent=1))
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=pathlib.Path, default=ROOT / "backups")
    ap.add_argument("--keep", type=int, default=7)
    a = ap.parse_args()
    run_backup(a.dir, a.keep)


if __name__ == "__main__":
    main()

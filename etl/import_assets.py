"""Import a CSV file of assets through the staging pipeline: load -> validate -> promote.

    python etl/import_assets.py data/incoming/osm_roads.csv
    python etl/import_assets.py data/incoming/sample_with_errors.csv --validate-only

The source of the geometry (OpenStreetMap or synthetic) is taken from the file name prefix ("osm_" or
"synthetic_"), or given with --geometry-source. Attributes are always recorded as synthetic in this demonstration.
Connects as the ETL login role (GAZ_ETL_USER, default etl_runner): it can write to staging and run the two
pipeline functions, and has no direct rights on the register.
"""
import argparse
import csv
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from gaz.db import connect  # noqa: E402

COLS = ["row_no", "asset_code", "asset_name", "type_code", "status_code", "install_date", "wkt", "lon", "lat", "source_ref", "details"]


def import_file(path: pathlib.Path, geometry_source: str | None = None, validate_only: bool = False, user: str | None = None, quiet=False):
    geometry_source = geometry_source or ("SYNTHETIC" if path.name.startswith("synthetic_") else "OSM")
    user = user or os.environ.get("GAZ_ETL_USER", "etl_runner")
    password = os.environ.get("GAZ_ETL_PASSWORD")
    with connect(user=user, password=password, app="import_assets") as conn:
        batch = conn.execute(
            "INSERT INTO staging.import_batches (source_file, geometry_source_code, attribute_source_code) VALUES (%s, %s, 'SYNTHETIC') RETURNING batch_id",
            (path.name, geometry_source)).fetchone()[0]
        n = 0
        with path.open(encoding="utf-8", newline="") as f, \
                conn.cursor().copy(f"COPY staging.incoming_assets (batch_id, {', '.join(COLS)}) FROM STDIN") as cp:
            for n, row in enumerate(csv.DictReader(f), 1):
                cp.write_row([batch, n] + [row.get(c) or None for c in COLS[1:-1]] + [row.get("details") or "{}"])
        failures = conn.execute("SELECT * FROM staging.validate_batch(%s)", (batch,)).fetchall()
        valid = conn.execute("SELECT rows_valid FROM staging.import_batches WHERE batch_id = %s", (batch,)).fetchone()[0]
        promoted = 0
        if not validate_only:
            promoted = conn.execute("SELECT staging.promote_batch(%s)", (batch,)).fetchone()[0]
        conn.commit()
    if not quiet:
        msg = f"batch {batch:4d}  {path.name:32s} rows {n:6d}  valid {valid:6d}  promoted {promoted:6d}"
        print(msg + ("".join(f"\n      {code}: {cnt} rows" for code, cnt in failures)))
    return {"batch_id": batch, "rows": n, "valid": valid, "promoted": promoted, "failures": dict(failures)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", type=pathlib.Path)
    ap.add_argument("--geometry-source", choices=["OSM", "SYNTHETIC"])
    ap.add_argument("--validate-only", action="store_true")
    a = ap.parse_args()
    for p in a.files:
        import_file(p, a.geometry_source, a.validate_only)


if __name__ == "__main__":
    main()

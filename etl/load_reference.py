"""Load reference data (lookups) and MDB ward boundaries. Run as the database owner or a superuser.

    python etl/load_reference.py

Does nothing if reference data is already present, so it is safe to run on every start-up.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gaz.db import connect  # noqa: E402


def main():
    with connect(app="load_reference") as conn:
        if conn.execute("SELECT count(*) FROM reference.asset_types").fetchone()[0]:
            print("Reference data already loaded.")
            return
        conn.execute((ROOT / "database" / "seed_data" / "reference_data.sql").read_text(encoding="utf-8"))
        wards = json.loads((ROOT / "data" / "reference" / "wards_tsh.geojson").read_text(encoding="utf-8"))
        with conn.cursor() as cur:
            for f in wards["features"]:
                p = f["properties"]
                cur.execute("""INSERT INTO reference.wards (ward_id, municipality_code, ward_no, in_study_area, demarcation_year, source_code, geom)
                               VALUES (%s, 'TSH', %s, %s, 2026, 'MDB', ST_Multi(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))))""",
                            (p["ward_id"], p["ward_no"], p["in_study_area"], json.dumps(f["geometry"])))
        conn.commit()
        n = conn.execute("SELECT count(*), count(*) FILTER (WHERE in_study_area) FROM reference.wards").fetchone()
        print(f"Reference data loaded: {n[0]} wards, {n[1]} in the study area.")


if __name__ == "__main__":
    main()

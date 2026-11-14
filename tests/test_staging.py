"""The import pipeline: a file with deliberate errors must be loaded, every error logged, and only clean rows promoted."""
import csv
import pathlib

import psycopg
import pytest

SAMPLE = pathlib.Path(__file__).resolve().parents[1] / "data" / "incoming" / "sample_with_errors.csv"
COLS = ["asset_code", "asset_name", "type_code", "status_code", "install_date", "wkt", "lon", "lat", "source_ref", "details"]

EXPECTED = {           # row number -> rules it must fail
    2: {"R01"}, 3: {"R02"}, 4: {"R03"}, 5: {"R04"}, 6: {"R05"}, 7: {"R06"}, 8: {"R07"}, 9: {"R08"}, 10: {"R09"},
    11: {"R10"}, 12: {"R10"}, 13: {"R12"},
    14: {"R99"},       # passes the rules, then fails the wattage CHECK constraint on promotion
}


def load_sample(conn):
    batch = conn.execute("INSERT INTO staging.import_batches (source_file, geometry_source_code, attribute_source_code) "
                         "VALUES ('sample_with_errors.csv', 'SYNTHETIC', 'SYNTHETIC') RETURNING batch_id").fetchone()[0]
    with SAMPLE.open(encoding="utf-8", newline="") as f:
        for n, row in enumerate(csv.DictReader(f), 1):
            conn.execute(f"INSERT INTO staging.incoming_assets (batch_id, row_no, {', '.join(COLS)}) VALUES (%s, %s, {', '.join(['%s'] * len(COLS))})",
                         [batch, n] + [row[c] or None for c in COLS[:-1]] + [row["details"] or "{}"])
    return batch


def test_validation_and_promotion(as_role):
    c = as_role("etl_runner")
    batch = load_sample(c)
    c.execute("SELECT * FROM staging.validate_batch(%s)", (batch,)).fetchall()
    promoted = c.execute("SELECT staging.promote_batch(%s)", (batch,)).fetchone()[0]

    got = {}
    for row_no, rule in c.execute("SELECT row_no, rule_code FROM staging.import_rejections WHERE batch_id = %s", (batch,)):
        got.setdefault(row_no, set()).add(rule)
    assert got == EXPECTED
    assert promoted == 2                                          # rows 1 and 15
    status, total, rejected = c.execute("SELECT status, rows_total, rows_rejected FROM staging.import_batches WHERE batch_id = %s", (batch,)).fetchone()
    assert (status, total, rejected) == ("PROMOTED", 15, 13)


def test_promoted_rows_land_in_register_with_details(db):
    """Run the pipeline as the owner in one transaction so the new register rows can be checked directly."""
    batch = load_sample(db)
    db.execute("SELECT * FROM staging.validate_batch(%s)", (batch,)).fetchall()
    db.execute("SELECT staging.promote_batch(%s)", (batch,))
    rows = db.execute("""SELECT a.type_code, a.ward_id, a.geometry_source_code, s.lamp_type, w.diameter_mm
                           FROM staging.incoming_assets i JOIN assets.infrastructure_assets a ON a.asset_id = i.promoted_asset_id
                           LEFT JOIN assets.streetlights s USING (asset_id) LEFT JOIN assets.water_assets w USING (asset_id)
                          WHERE i.batch_id = %s ORDER BY i.row_no""", (batch,)).fetchall()
    assert rows == [("STREETLIGHT", "79900056", "SYNTHETIC", "LED", None), ("HYDRANT", "79900056", "SYNTHETIC", None, 80)]


def test_promotion_requires_validation(as_role):
    c = as_role("etl_runner")
    batch = load_sample(c)
    with pytest.raises(psycopg.errors.RaiseException):
        with c.transaction():
            c.execute("SELECT staging.promote_batch(%s)", (batch,))

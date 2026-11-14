"""Data integrity: the database itself must reject invalid records, whatever program sends them."""
from conftest import HATFIELD, JOHANNESBURG, errors, raises

INSERT_ASSET = """INSERT INTO assets.infrastructure_assets (asset_code, type_code, ward_id, install_date, status_code,
                  decommission_date, geometry_source_code, attribute_source_code, geom)
                  VALUES (%(code)s, %(type)s, NULL, %(installed)s, %(status)s, %(decommissioned)s, 'SYNTHETIC', 'SYNTHETIC', {geom})"""


def asset(code=None, type_="STREETLIGHT", installed="2020-01-01", status="ACTIVE", decommissioned=None):
    return {"code": code, "type": type_, "installed": installed, "status": status, "decommissioned": decommissioned}


# --- things that must work ---------------------------------------------------------------------------------------

def test_valid_asset_gets_code_and_ward(db):
    code, ward = db.execute(INSERT_ASSET.format(geom=HATFIELD) + " RETURNING asset_code, ward_id", asset()).fetchone()
    assert code.startswith("SL-") and len(code) == 9
    assert ward == "79900056"


def test_update_is_audited_with_changed_fields(db, sample):
    aid, code = sample["streetlight"]
    db.execute("UPDATE assets.infrastructure_assets SET asset_name = 'Test lamp' WHERE asset_id = %s", (aid,))
    row = db.execute("""SELECT operation, changed_fields, new_row ->> 'asset_name' FROM audit.change_log
                         WHERE table_name = 'infrastructure_assets' AND row_key = %s ORDER BY log_id DESC LIMIT 1""", (str(aid),)).fetchone()
    assert row == ("UPDATE", ["asset_name"], "Test lamp")


def test_update_without_change_is_not_audited(db, sample):
    aid, _ = sample["streetlight"]
    before = db.execute("SELECT count(*) FROM audit.change_log").fetchone()[0]
    db.execute("UPDATE assets.infrastructure_assets SET asset_name = asset_name WHERE asset_id = %s", (aid,))
    assert db.execute("SELECT count(*) FROM audit.change_log").fetchone()[0] == before


# --- assets ------------------------------------------------------------------------------------------------------

def test_reject_bad_code_format(db):
    raises(db, errors.CheckViolation, INSERT_ASSET.format(geom=HATFIELD), asset(code="SL-12"))


def test_reject_code_prefix_for_wrong_type(db):
    raises(db, errors.CheckViolation, INSERT_ASSET.format(geom=HATFIELD), asset(code="HY-999001"))


def test_reject_duplicate_code(db, sample):
    raises(db, errors.UniqueViolation, INSERT_ASSET.format(geom=HATFIELD), asset(code=sample["streetlight"][1]))


def test_reject_unknown_type(db):
    raises(db, errors.ForeignKeyViolation, INSERT_ASSET.format(geom=HATFIELD), asset(type_="SPACESHIP"))


def test_reject_wrong_geometry_type(db):
    line = "ST_SetSRID(ST_MakeLine(ST_MakePoint(28.2370, -25.7480), ST_MakePoint(28.2380, -25.7485)), 4326)"
    raises(db, errors.CheckViolation, INSERT_ASSET.format(geom=line), asset(type_="STREETLIGHT"))


def test_reject_outside_study_area(db):
    raises(db, errors.CheckViolation, INSERT_ASSET.format(geom=JOHANNESBURG), asset())


def test_reject_wrong_srid(db):
    raises(db, errors.InvalidParameterValue, INSERT_ASSET.format(geom="ST_Transform(" + HATFIELD + ", 32735)"), asset())


def test_reject_invalid_polygon(db):
    bowtie = "ST_GeomFromText('POLYGON((28.236 -25.748, 28.238 -25.746, 28.238 -25.748, 28.236 -25.746, 28.236 -25.748))', 4326)"
    raises(db, errors.CheckViolation, INSERT_ASSET.format(geom=bowtie), asset(type_="PARK"))


def test_reject_install_date_in_future(db):
    raises(db, errors.CheckViolation, INSERT_ASSET.format(geom=HATFIELD), asset(installed="2099-01-01"))


def test_reject_decommissioned_without_date(db):
    raises(db, errors.CheckViolation, INSERT_ASSET.format(geom=HATFIELD), asset(status="DECOMMISSIONED"))


def test_reject_decommission_before_install(db):
    raises(db, errors.CheckViolation, INSERT_ASSET.format(geom=HATFIELD), asset(status="DECOMMISSIONED", decommissioned="2010-01-01"))


def test_reject_detail_row_in_wrong_table(db, sample):
    road_id = sample["road"][0]
    raises(db, errors.CheckViolation,
           "INSERT INTO assets.streetlights VALUES (%s, 'LED', 60, 8, 'Steel')", (road_id,))


def test_reject_out_of_range_detail(db):
    new_id = db.execute(INSERT_ASSET.format(geom=HATFIELD) + " RETURNING asset_id", asset()).fetchone()[0]
    raises(db, errors.CheckViolation, "INSERT INTO assets.streetlights VALUES (%s, 'LED', 5000, 8, 'Steel')", (new_id,))


def test_cannot_delete_asset_with_history(db, sample):
    raises(db, errors.ForeignKeyViolation, "DELETE FROM assets.infrastructure_assets WHERE asset_id = %s", (sample["streetlight"][0],))


# --- maintenance -------------------------------------------------------------------------------------------------

def test_reject_inspection_of_missing_asset(db):
    raises(db, errors.ForeignKeyViolation,
           "INSERT INTO maintenance.inspections (asset_id, inspected_on, condition_grade) VALUES (-1, '2025-01-01', 2)")


def test_reject_inspection_before_install(db, sample):
    raises(db, errors.CheckViolation,
           "INSERT INTO maintenance.inspections (asset_id, inspected_on, condition_grade) VALUES (%s, '1901-01-01', 2)", (sample["streetlight"][0],))


def test_reject_poor_grade_without_defect(db, sample):
    raises(db, errors.CheckViolation,
           "INSERT INTO maintenance.inspections (asset_id, inspected_on, condition_grade) VALUES (%s, '2026-11-01', 5)", (sample["streetlight"][0],))


def test_reject_defect_from_other_class(db, sample):
    raises(db, errors.CheckViolation,
           "INSERT INTO maintenance.inspections (asset_id, inspected_on, condition_grade, defect_code) VALUES (%s, '2026-11-01', 4, 'WT_BURST')",
           (sample["streetlight"][0],))


def test_reject_grade_outside_scale(db, sample):
    raises(db, errors.ForeignKeyViolation,
           "INSERT INTO maintenance.inspections (asset_id, inspected_on, condition_grade) VALUES (%s, '2026-11-01', 0)", (sample["streetlight"][0],))


def test_reject_negative_cost(db, sample):
    raises(db, errors.CheckViolation,
           "INSERT INTO maintenance.maintenance_costs (work_order_id, cost_type, cost_status, amount_zar, cost_date) VALUES (%s, 'LABOUR', 'ACTUAL', -100, '2026-01-01')",
           (sample["work_order"],))


def test_reject_completed_work_order_without_date(db, sample):
    raises(db, errors.CheckViolation,
           "UPDATE maintenance.work_orders SET completed_on = NULL WHERE work_order_id = %s", (sample["work_order"],))


def test_reject_completion_before_raised(db, sample):
    raises(db, errors.CheckViolation,
           "UPDATE maintenance.work_orders SET completed_on = raised_on - 5 WHERE work_order_id = %s", (sample["work_order"],))


def test_work_order_number_and_target_generated(db, sample):
    wo, target, raised = db.execute("""INSERT INTO maintenance.work_orders (asset_id, wo_type, priority_code, raised_on, description)
                                       VALUES (%s, 'CORRECTIVE', 'P2', '2026-11-02', 'test') RETURNING wo_number, target_date, raised_on""",
                                    (sample["streetlight"][0],)).fetchone()
    assert wo.startswith("WO-2026-") and (target - raised).days == 7

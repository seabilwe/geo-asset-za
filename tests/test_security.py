"""Access control: each login role can do its job and nothing else."""
from conftest import errors, raises


# --- public web application --------------------------------------------------------------------------------------

def test_web_reads_api_views(as_role):
    c = as_role("web_app")
    assert c.execute("SELECT count(*) FROM api.assets").fetchone()[0] > 10000
    assert c.execute("SELECT total_assets FROM api.kpis").fetchone()[0] > 10000


def test_web_cannot_read_base_tables(as_role):
    c = as_role("web_app")
    for table in ("assets.infrastructure_assets", "maintenance.inspections", "audit.change_log", "staging.incoming_assets", "admin.backup_log"):
        raises(c, errors.InsufficientPrivilege, f"SELECT 1 FROM {table} LIMIT 1")


def test_web_session_is_read_only(as_role):
    c = as_role("web_app")
    assert c.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
    assert c.execute("SHOW statement_timeout").fetchone()[0] == "5s"


def test_web_cannot_run_pipeline_functions(as_role):
    c = as_role("web_app")
    raises(c, errors.InsufficientPrivilege, "SELECT staging.promote_batch(1)")
    raises(c, errors.InsufficientPrivilege, "SELECT operations.refresh_reporting()")


def test_api_hides_people(as_role):
    c = as_role("web_app")
    cols = {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'api'")}
    assert not cols & {"inspector", "created_by", "updated_by", "db_user", "asset_id"}


# --- analyst -----------------------------------------------------------------------------------------------------

def test_analyst_reads_reporting_not_base_tables(as_role):
    c = as_role("analyst_demo")
    assert c.execute("SELECT count(*) FROM operations.maintenance_priority_summary").fetchone()[0] > 0
    raises(c, errors.InsufficientPrivilege, "SELECT 1 FROM maintenance.work_orders LIMIT 1")
    raises(c, errors.InsufficientPrivilege, "UPDATE operations.asset_condition_summary SET assets = 0")


# --- field inspector ---------------------------------------------------------------------------------------------

def test_inspector_records_own_inspection(as_role, sample):
    c = as_role("inspector_a")
    c.execute("INSERT INTO maintenance.inspections (asset_id, inspected_on, condition_grade) VALUES (%s, current_date, 2)", (sample["streetlight"][0],))
    assert c.execute("SELECT inspector FROM maintenance.inspections WHERE asset_id = %s AND inspected_on = current_date",
                     (sample["streetlight"][0],)).fetchone()[0] == "inspector_a"


def test_inspector_cannot_record_in_another_name(as_role, sample):
    c = as_role("inspector_a")
    raises(c, errors.InsufficientPrivilege,     # row-level security: new row violates policy
           "INSERT INTO maintenance.inspections (asset_id, inspected_on, condition_grade, inspector) VALUES (%s, current_date, 2, 'inspector_b')",
           (sample["streetlight"][0],))


def test_inspector_cannot_edit_others_inspections(as_role, sample):
    c = as_role("inspector_a")
    assert c.execute("SELECT count(*) FROM maintenance.inspections WHERE inspection_id = %s", (sample["inspection_b"],)).fetchone()[0] == 1  # can see it
    cur = c.execute("UPDATE maintenance.inspections SET notes = 'changed' WHERE inspection_id = %s", (sample["inspection_b"],))
    assert cur.rowcount == 0                                                                                                                  # cannot change it


def test_inspector_may_change_status_only(as_role, sample):
    c = as_role("inspector_a")
    aid = sample["streetlight"][0]
    assert c.execute("UPDATE assets.infrastructure_assets SET status_code = 'OUT_OF_SERVICE' WHERE asset_id = %s", (aid,)).rowcount == 1
    raises(c, errors.InsufficientPrivilege, "UPDATE assets.infrastructure_assets SET asset_name = 'x' WHERE asset_id = %s", (aid,))
    raises(c, errors.InsufficientPrivilege, "DELETE FROM assets.infrastructure_assets WHERE asset_id = %s", (aid,))
    raises(c, errors.InsufficientPrivilege, "INSERT INTO maintenance.work_orders (asset_id, wo_type, priority_code, raised_on, description) "
                                            "VALUES (%s, 'CORRECTIVE', 'P3', current_date, 'x')", (aid,))


def test_inspector_change_is_stamped_and_log_is_out_of_reach(as_role, sample):
    c = as_role("inspector_a")
    aid = sample["streetlight"][0]
    c.execute("UPDATE assets.infrastructure_assets SET status_code = 'OUT_OF_SERVICE' WHERE asset_id = %s", (aid,))
    assert c.execute("SELECT updated_by FROM assets.infrastructure_assets WHERE asset_id = %s", (aid,)).fetchone()[0] == "inspector_a"
    raises(c, errors.InsufficientPrivilege, "SELECT 1 FROM audit.change_log LIMIT 1")
    raises(c, errors.InsufficientPrivilege, "DELETE FROM audit.change_log")


# --- manager -----------------------------------------------------------------------------------------------------

def test_manager_edits_but_never_deletes_assets(as_role, sample):
    c = as_role("manager_demo")
    aid = sample["road"][0]
    assert c.execute("UPDATE assets.infrastructure_assets SET asset_name = 'Renamed' WHERE asset_id = %s", (aid,)).rowcount == 1
    raises(c, errors.InsufficientPrivilege, "DELETE FROM assets.infrastructure_assets WHERE asset_id = %s", (aid,))
    raises(c, errors.InsufficientPrivilege, "UPDATE reference.asset_types SET criticality = 1")
    raises(c, errors.InsufficientPrivilege, "DELETE FROM audit.change_log")


# --- ETL and monitoring ------------------------------------------------------------------------------------------

def test_etl_has_no_direct_access_to_register(as_role):
    c = as_role("etl_runner")
    raises(c, errors.InsufficientPrivilege, "SELECT 1 FROM assets.infrastructure_assets LIMIT 1")
    raises(c, errors.InsufficientPrivilege, "INSERT INTO assets.infrastructure_assets (type_code) VALUES ('STREETLIGHT')")


def test_monitor_reads_health_only(as_role):
    c = as_role("monitor")
    metrics = {r[0] for r in c.execute("SELECT metric FROM admin.v_health")}
    assert {"Database size", "Last successful backup", "Cache hit ratio"} <= metrics
    raises(c, errors.InsufficientPrivilege, "SELECT 1 FROM assets.infrastructure_assets LIMIT 1")


def test_no_privileges_left_to_public(db):
    """No application table, view or function is granted to PUBLIC."""
    leaks = db.execute("""
        SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace,
               aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
         WHERE n.nspname IN ('reference','assets','maintenance','operations','audit','staging','api','admin') AND a.grantee = 0
        UNION ALL
        SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace,
               aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
         WHERE n.nspname IN ('reference','assets','maintenance','operations','audit','staging','api','admin') AND a.grantee = 0""").fetchall()
    assert leaks == []


def test_objects_owned_by_owner_role(db):
    owners = {r[0] for r in db.execute("""SELECT DISTINCT pg_get_userbyid(c.relowner) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                                           WHERE n.nspname IN ('reference','assets','maintenance','operations','audit','staging','api','admin')
                                             AND c.relkind IN ('r','v','m')""")}
    assert owners == {"gaz_owner"}

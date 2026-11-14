-- V014  Close a gap found by tests/test_security.py::test_no_privileges_left_to_public
-- admin.apply_ownership() was created in V013, after V011 had revoked EXECUTE from PUBLIC on the functions that
-- existed then, so PostgreSQL's default grant (EXECUTE to PUBLIC) applied to it. Applied migrations are never
-- edited, so the fix is this new migration. The function is now callable only by its owner and superusers.

REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA reference, assets, maintenance, operations, audit, staging, api, admin FROM PUBLIC;

-- Re-grant what V011 granted deliberately (REVOKE ... FROM PUBLIC does not touch these, listed for clarity).
GRANT EXECUTE ON FUNCTION operations.refresh_reporting() TO gaz_manager;
GRANT EXECUTE ON FUNCTION staging.validate_batch(bigint), staging.promote_batch(bigint),
                          staging.try_date(text), staging.try_geom(text, text, text) TO gaz_etl;

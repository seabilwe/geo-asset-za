-- V005  Audit trail
-- One generic trigger function writes every insert, update and delete on the register and maintenance tables
-- to audit.change_log as JSON. The function is SECURITY DEFINER, so users can write audit rows through it
-- without holding any privilege on the audit table itself, and nobody but the owner can alter the log.

CREATE TABLE audit.change_log (
    log_id          bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    changed_at      timestamptz  NOT NULL DEFAULT clock_timestamp(),
    transaction_id  bigint       NOT NULL DEFAULT txid_current(),
    db_user         name         NOT NULL,
    session_user_name name       NOT NULL DEFAULT session_user,
    application     text         DEFAULT current_setting('application_name', true),
    schema_name     name         NOT NULL,
    table_name      name         NOT NULL,
    operation       varchar(6)   NOT NULL CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
    row_key         text         NOT NULL,
    changed_fields  text[],
    old_row         jsonb,
    new_row         jsonb
);
COMMENT ON TABLE  audit.change_log IS 'Append-only history of changes to the asset register and maintenance records.';
COMMENT ON COLUMN audit.change_log.db_user IS 'Role that made the change (current_user at the time).';
COMMENT ON COLUMN audit.change_log.changed_fields IS 'For updates, the columns whose values changed.';

CREATE INDEX change_log_table_key_idx ON audit.change_log (schema_name, table_name, row_key);
CREATE INDEX change_log_changed_at_idx ON audit.change_log USING brin (changed_at);

CREATE FUNCTION audit.log_change() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    o jsonb := CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN to_jsonb(OLD) END;
    n jsonb := CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN to_jsonb(NEW) END;
    key_col text := TG_ARGV[0];
    changed text[];
BEGIN
    -- geometry is logged as a hash-sized summary rather than full coordinates, to keep the log small
    IF o ? 'geom' THEN o := jsonb_set(o, '{geom}', to_jsonb(md5(OLD.geom::text))); END IF;
    IF n ? 'geom' THEN n := jsonb_set(n, '{geom}', to_jsonb(md5(NEW.geom::text))); END IF;
    IF TG_OP = 'UPDATE' THEN
        SELECT array_agg(k ORDER BY k) INTO changed
          FROM jsonb_object_keys(n) k
         WHERE n -> k IS DISTINCT FROM o -> k AND k NOT IN ('updated_at', 'updated_by');
        IF changed IS NULL THEN RETURN NULL; END IF;     -- nothing real changed: do not log
    END IF;
    INSERT INTO audit.change_log (db_user, schema_name, table_name, operation, row_key, changed_fields, old_row, new_row)
    VALUES (current_user, TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP, coalesce(n, o) ->> key_col, changed, o, n);
    RETURN NULL;
END $$;
COMMENT ON FUNCTION audit.log_change() IS 'Generic AFTER ROW trigger. The argument names the key column to record as row_key.';

DO $$
DECLARE r record;
BEGIN
    FOR r IN SELECT * FROM (VALUES
        ('assets', 'infrastructure_assets', 'asset_id'), ('assets', 'streetlights', 'asset_id'),
        ('assets', 'road_segments', 'asset_id'), ('assets', 'water_assets', 'asset_id'),
        ('assets', 'electrical_assets', 'asset_id'), ('assets', 'stormwater_assets', 'asset_id'),
        ('assets', 'public_facilities', 'asset_id'),
        ('maintenance', 'inspections', 'inspection_id'), ('maintenance', 'work_orders', 'work_order_id'),
        ('maintenance', 'maintenance_activities', 'activity_id'), ('maintenance', 'maintenance_costs', 'cost_id')) v(s, t, k)
    LOOP
        EXECUTE format('CREATE TRIGGER audit_change AFTER INSERT OR UPDATE OR DELETE ON %I.%I
                        FOR EACH ROW EXECUTE FUNCTION audit.log_change(%L)', r.s, r.t, r.k);
    END LOOP;
END $$;

-- Switch auditing off for bulk loads, which are recorded once per batch in staging.import_batches instead.
-- Only the owner can call this (privileges are set in V011).
CREATE FUNCTION audit.set_enabled(enabled boolean) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE r record;
BEGIN
    FOR r IN SELECT event_object_schema s, event_object_table t FROM information_schema.triggers
              WHERE trigger_name = 'audit_change' GROUP BY 1, 2 LOOP
        EXECUTE format('ALTER TABLE %I.%I %s TRIGGER audit_change', r.s, r.t, CASE WHEN enabled THEN 'ENABLE' ELSE 'DISABLE' END);
    END LOOP;
END $$;

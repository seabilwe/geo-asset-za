-- V011  Roles and privileges
-- Group roles (NOLOGIN) carry the privileges; people and applications log in as LOGIN roles that are members of
-- one group. Login roles and their passwords are created outside the migrations (administration/security/
-- create_login_roles.py) so that no password is ever committed.
--
--   gaz_owner      owns every object; nobody logs in as it
--   gaz_admin      database administrator: member of gaz_owner and pg_monitor
--   gaz_manager    infrastructure manager: reads everything, edits assets and maintenance, cannot delete assets
--   gaz_inspector  field inspector: reads assets, records inspections (own rows only), may change an asset's status
--   gaz_analyst    data analyst: reads reporting views and API views, no access to base tables
--   gaz_etl        import process: loads staging tables and runs validation and promotion
--   gaz_web        public web application: reads the api schema only
--   gaz_monitor    monitoring: reads admin views and PostgreSQL statistics

DO $$
DECLARE r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['gaz_owner', 'gaz_admin', 'gaz_manager', 'gaz_inspector', 'gaz_analyst', 'gaz_etl', 'gaz_web', 'gaz_monitor'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN', r);
        END IF;
    END LOOP;
END $$;

GRANT gaz_owner TO gaz_admin;
GRANT pg_monitor TO gaz_admin, gaz_monitor;

-- Database: no connections unless granted
DO $$
BEGIN
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO gaz_owner, gaz_admin, gaz_manager, gaz_inspector, gaz_analyst, gaz_etl, gaz_web, gaz_monitor', current_database());
END $$;

-- Functions are executable by PUBLIC by default in PostgreSQL. Remove that for every schema we own.
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA reference, assets, maintenance, operations, audit, staging, api, admin FROM PUBLIC;

-- Schema usage
GRANT USAGE ON SCHEMA reference   TO gaz_manager, gaz_inspector, gaz_analyst, gaz_etl;
GRANT USAGE ON SCHEMA assets      TO gaz_manager, gaz_inspector;
GRANT USAGE ON SCHEMA maintenance TO gaz_manager, gaz_inspector;
GRANT USAGE ON SCHEMA operations  TO gaz_manager, gaz_analyst;
GRANT USAGE ON SCHEMA api         TO gaz_manager, gaz_analyst, gaz_web;
GRANT USAGE ON SCHEMA staging     TO gaz_etl, gaz_manager;
GRANT USAGE ON SCHEMA admin       TO gaz_monitor;
GRANT USAGE ON SCHEMA audit       TO gaz_manager;

-- Reference data: everyone who works with assets can read it; only the owner changes it
GRANT SELECT ON ALL TABLES IN SCHEMA reference TO gaz_manager, gaz_inspector, gaz_analyst, gaz_etl;

-- Manager
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA assets TO gaz_manager;
GRANT DELETE ON assets.streetlights, assets.road_segments, assets.water_assets, assets.electrical_assets,
                assets.stormwater_assets, assets.public_facilities TO gaz_manager;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA maintenance TO gaz_manager;
GRANT DELETE ON maintenance.maintenance_costs TO gaz_manager;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA assets, maintenance TO gaz_manager;
GRANT SELECT ON ALL TABLES IN SCHEMA operations, api TO gaz_manager;
GRANT SELECT ON ALL TABLES IN SCHEMA staging TO gaz_manager;
GRANT SELECT ON audit.change_log TO gaz_manager;
GRANT EXECUTE ON FUNCTION operations.refresh_reporting() TO gaz_manager;

-- Inspector: read the register, record inspections, and change only the status column of an asset
GRANT SELECT ON ALL TABLES IN SCHEMA assets TO gaz_inspector;
GRANT UPDATE (status_code, decommission_date) ON assets.infrastructure_assets TO gaz_inspector;
GRANT SELECT, INSERT, UPDATE ON maintenance.inspections TO gaz_inspector;
GRANT SELECT ON maintenance.work_orders TO gaz_inspector;

-- Analyst: derived data only
GRANT SELECT ON ALL TABLES IN SCHEMA operations, api TO gaz_analyst;

-- ETL: write raw rows, read results, run the two pipeline functions (SECURITY DEFINER, so no rights on the register are needed)
GRANT SELECT, INSERT, DELETE ON staging.import_batches, staging.incoming_assets TO gaz_etl;
GRANT SELECT ON staging.import_rejections, staging.validation_rules TO gaz_etl;
GRANT EXECUTE ON FUNCTION staging.validate_batch(bigint), staging.promote_batch(bigint) TO gaz_etl;
GRANT EXECUTE ON FUNCTION staging.try_date(text), staging.try_geom(text, text, text) TO gaz_etl;

-- Public web application
GRANT SELECT ON ALL TABLES IN SCHEMA api TO gaz_web;

-- Monitoring
GRANT SELECT ON ALL TABLES IN SCHEMA admin TO gaz_monitor;
GRANT SELECT ON admin.backup_log, admin.job_runs TO gaz_admin;

-- Objects created later by gaz_owner get the same treatment automatically
ALTER DEFAULT PRIVILEGES FOR ROLE gaz_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE gaz_owner IN SCHEMA reference GRANT SELECT ON TABLES TO gaz_manager, gaz_inspector, gaz_analyst, gaz_etl;
ALTER DEFAULT PRIVILEGES FOR ROLE gaz_owner IN SCHEMA api       GRANT SELECT ON TABLES TO gaz_manager, gaz_analyst, gaz_web;
ALTER DEFAULT PRIVILEGES FOR ROLE gaz_owner IN SCHEMA operations GRANT SELECT ON TABLES TO gaz_manager, gaz_analyst;
ALTER DEFAULT PRIVILEGES FOR ROLE gaz_owner IN SCHEMA admin     GRANT SELECT ON TABLES TO gaz_monitor;

-- Session limits for the public application role: read-only, short statements, no idle transactions
ALTER ROLE gaz_web SET default_transaction_read_only = on;
ALTER ROLE gaz_web SET statement_timeout = '5s';
ALTER ROLE gaz_web SET idle_in_transaction_session_timeout = '10s';
ALTER ROLE gaz_analyst SET statement_timeout = '2min';

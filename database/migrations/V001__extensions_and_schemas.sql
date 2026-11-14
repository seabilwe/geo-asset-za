-- V001  Extensions and schemas
-- GEO-ASSET ZA keeps each responsibility in its own schema so that privileges can be granted per schema
-- rather than per table, and so that raw, unvalidated data never sits next to production records.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;   -- query statistics for the monitoring views (needs shared_preload_libraries)

-- Nobody gets anything by default: PostgreSQL grants CREATE and USAGE on "public" to every role unless told otherwise.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO PUBLIC;              -- PostGIS functions and types live here and must stay callable

CREATE SCHEMA IF NOT EXISTS reference;
CREATE SCHEMA IF NOT EXISTS assets;
CREATE SCHEMA IF NOT EXISTS maintenance;
CREATE SCHEMA IF NOT EXISTS operations;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS api;
CREATE SCHEMA IF NOT EXISTS admin;

COMMENT ON SCHEMA reference   IS 'Boundaries and lookup tables: wards, asset classes and types, condition grades, statuses, priorities and data sources.';
COMMENT ON SCHEMA assets      IS 'The asset register: one row per asset in assets.infrastructure_assets, with one detail table per asset family.';
COMMENT ON SCHEMA maintenance IS 'Inspections (condition assessments), work orders, maintenance activities and costs.';
COMMENT ON SCHEMA operations  IS 'Derived reporting: latest condition per asset, condition and priority summaries for managers and analysts.';
COMMENT ON SCHEMA audit       IS 'Row-level change history written by triggers on the assets and maintenance tables.';
COMMENT ON SCHEMA staging     IS 'Incoming batches of asset records, held here until they pass validation and are promoted to the register.';
COMMENT ON SCHEMA api         IS 'Read-only views for the public web application. The only schema the public application role can read.';
COMMENT ON SCHEMA admin       IS 'Database administration: migrations, backup log, and monitoring views.';

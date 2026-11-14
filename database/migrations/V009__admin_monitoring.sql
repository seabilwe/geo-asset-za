-- V009  Administration: job and backup logs, monitoring views, reporting refresh
-- The monitoring views read PostgreSQL's statistics views (pg_stat_*). The gaz_monitor role gets them through
-- the predefined pg_monitor role, so monitoring does not need a superuser.

CREATE TABLE admin.backup_log (
    backup_id     bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind          varchar(12)  NOT NULL CHECK (kind IN ('BACKUP', 'RESTORE_TEST')),
    started_at    timestamptz  NOT NULL,
    finished_at   timestamptz,
    status        varchar(8)   NOT NULL CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED')),
    file_name     varchar(255),
    size_bytes    bigint       CHECK (size_bytes >= 0),
    sha256        char(64),
    details       jsonb        NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT backup_finished_after_start CHECK (finished_at IS NULL OR finished_at >= started_at)
);
COMMENT ON TABLE admin.backup_log IS 'Every backup and every restore test, written by administration/backup and administration/restore.';

CREATE TABLE admin.job_runs (
    run_id       bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_name     varchar(60)  NOT NULL,
    started_at   timestamptz  NOT NULL DEFAULT clock_timestamp(),
    finished_at  timestamptz,
    status       varchar(8)   NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED')),
    rows_affected bigint,
    message      text
);
COMMENT ON TABLE admin.job_runs IS 'Log of scheduled and automated jobs: imports, reporting refreshes, backups.';

CREATE FUNCTION operations.refresh_reporting() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE run bigint;
BEGIN
    INSERT INTO admin.job_runs (job_name) VALUES ('refresh_reporting') RETURNING run_id INTO run;
    REFRESH MATERIALIZED VIEW CONCURRENTLY operations.asset_condition_summary;
    REFRESH MATERIALIZED VIEW CONCURRENTLY operations.maintenance_priority_summary;
    UPDATE admin.job_runs SET finished_at = clock_timestamp(), status = 'SUCCESS',
           rows_affected = (SELECT count(*) FROM operations.maintenance_priority_summary)
     WHERE run_id = run;
END $$;
COMMENT ON FUNCTION operations.refresh_reporting() IS 'Refreshes both reporting materialized views without blocking readers and logs the run.';

-- Monitoring views ----------------------------------------------------------------------------------------------

CREATE VIEW admin.v_database_size AS
SELECT current_database() AS database, pg_database_size(current_database()) AS size_bytes,
       pg_size_pretty(pg_database_size(current_database())) AS size;

CREATE VIEW admin.v_table_sizes AS
SELECT n.nspname AS schema_name, c.relname AS table_name, c.reltuples::bigint AS approx_rows,
       pg_total_relation_size(c.oid) AS total_bytes,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
       pg_size_pretty(pg_indexes_size(c.oid)) AS index_size
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE c.relkind IN ('r', 'm') AND n.nspname IN ('reference', 'assets', 'maintenance', 'operations', 'audit', 'staging', 'admin')
 ORDER BY total_bytes DESC;
COMMENT ON VIEW admin.v_table_sizes IS 'Size of each table and materialized view, including indexes and TOAST.';

CREATE VIEW admin.v_connections AS
SELECT coalesce(usename, '(background)') AS role_name, coalesce(state, 'background') AS state, count(*) AS connections,
       max(now() - state_change) AS longest_in_state
  FROM pg_stat_activity WHERE datname = current_database() OR datname IS NULL
 GROUP BY 1, 2;
COMMENT ON VIEW admin.v_connections IS 'Connections by role and state. Many "idle in transaction" sessions point to an application bug.';

CREATE VIEW admin.v_long_running_queries AS
SELECT pid, usename AS role_name, state, now() - query_start AS running_for, wait_event_type, left(query, 300) AS query
  FROM pg_stat_activity
 WHERE datname = current_database() AND state <> 'idle' AND pid <> pg_backend_pid()
   AND now() - query_start > interval '30 seconds'
 ORDER BY running_for DESC;
COMMENT ON VIEW admin.v_long_running_queries IS 'Statements running for more than 30 seconds.';

CREATE VIEW admin.v_index_usage AS
SELECT s.schemaname AS schema_name, s.relname AS table_name, s.indexrelname AS index_name,
       s.idx_scan AS scans, pg_size_pretty(pg_relation_size(s.indexrelid)) AS index_size,
       (s.idx_scan = 0 AND NOT i.indisunique AND NOT i.indisprimary) AS unused_candidate
  FROM pg_stat_user_indexes s JOIN pg_index i ON i.indexrelid = s.indexrelid
 ORDER BY s.idx_scan;
COMMENT ON VIEW admin.v_index_usage IS 'Index scans since statistics were reset. Non-unique indexes never scanned are candidates for removal.';

CREATE VIEW admin.v_dead_tuples AS
SELECT schemaname AS schema_name, relname AS table_name, n_live_tup AS live_rows, n_dead_tup AS dead_rows,
       round(n_dead_tup::numeric / nullif(n_live_tup + n_dead_tup, 0) * 100, 1) AS dead_pct,
       last_autovacuum, last_vacuum, last_autoanalyze, last_analyze
  FROM pg_stat_user_tables
 ORDER BY n_dead_tup DESC;
COMMENT ON VIEW admin.v_dead_tuples IS 'Dead row versions left by updates and deletes, and when each table was last vacuumed and analysed.';

CREATE VIEW admin.v_cache_hit_ratio AS
SELECT round(sum(blks_hit)::numeric / nullif(sum(blks_hit + blks_read), 0) * 100, 2) AS cache_hit_pct
  FROM pg_stat_database WHERE datname = current_database();
COMMENT ON VIEW admin.v_cache_hit_ratio IS 'Share of block reads served from shared buffers. Below about 95% on a warm database suggests too little memory.';

CREATE VIEW admin.v_top_queries AS
SELECT left(regexp_replace(query, '\s+', ' ', 'g'), 200) AS query, calls,
       round(total_exec_time::numeric, 1) AS total_ms, round(mean_exec_time::numeric, 2) AS mean_ms, rows
  FROM pg_stat_statements
 WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
 ORDER BY total_exec_time DESC LIMIT 20;
COMMENT ON VIEW admin.v_top_queries IS 'The 20 statements with the most total execution time (pg_stat_statements).';

CREATE VIEW admin.v_backup_status AS
SELECT (SELECT max(finished_at) FROM admin.backup_log WHERE kind = 'BACKUP' AND status = 'SUCCESS') AS last_backup_at,
       (SELECT size_bytes FROM admin.backup_log WHERE kind = 'BACKUP' AND status = 'SUCCESS' ORDER BY finished_at DESC LIMIT 1) AS last_backup_bytes,
       (SELECT max(finished_at) FROM admin.backup_log WHERE kind = 'RESTORE_TEST' AND status = 'SUCCESS') AS last_restore_test_at,
       (SELECT count(*) FROM admin.backup_log WHERE status = 'FAILED' AND started_at > now() - interval '30 days') AS failures_30d;
COMMENT ON VIEW admin.v_backup_status IS 'Recovery readiness: age of the last good backup and last successful restore test.';

CREATE VIEW admin.v_failed_imports AS
SELECT b.batch_id, b.source_file, b.loaded_at, b.rows_total, b.rows_rejected, r.rule_code, v.description, count(*) AS rows_failed
  FROM staging.import_batches b
  JOIN staging.import_rejections r USING (batch_id)
  JOIN staging.validation_rules v USING (rule_code)
 GROUP BY 1, 2, 3, 4, 5, 6, 7
 ORDER BY b.loaded_at DESC, rows_failed DESC;
COMMENT ON VIEW admin.v_failed_imports IS 'Rejected rows per batch and rule.';

CREATE VIEW admin.v_health AS
WITH m AS (
    SELECT 'Database size' AS metric, (SELECT size FROM admin.v_database_size) AS value,
           CASE WHEN (SELECT size_bytes FROM admin.v_database_size) < 5e9 THEN 'OK' ELSE 'WARN' END AS status,
           'Warn above 5 GB' AS threshold
    UNION ALL
    SELECT 'Active connections', (SELECT count(*)::text FROM pg_stat_activity WHERE datname = current_database()),
           CASE WHEN (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database())
                     < 0.8 * current_setting('max_connections')::int THEN 'OK' ELSE 'WARN' END,
           'Warn above 80% of max_connections'
    UNION ALL
    SELECT 'Idle in transaction', (SELECT count(*)::text FROM pg_stat_activity WHERE state = 'idle in transaction' AND now() - state_change > interval '5 minutes'),
           CASE WHEN (SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction' AND now() - state_change > interval '5 minutes') = 0 THEN 'OK' ELSE 'WARN' END,
           'Warn on any session idle in a transaction for 5 minutes'
    UNION ALL
    SELECT 'Long-running queries', (SELECT count(*)::text FROM admin.v_long_running_queries),
           CASE WHEN (SELECT count(*) FROM admin.v_long_running_queries) = 0 THEN 'OK' ELSE 'WARN' END, 'Warn on any query over 30 s'
    UNION ALL
    SELECT 'Cache hit ratio', (SELECT cache_hit_pct || '%' FROM admin.v_cache_hit_ratio),
           CASE WHEN coalesce((SELECT cache_hit_pct FROM admin.v_cache_hit_ratio), 100) >= 95 THEN 'OK' ELSE 'WARN' END, 'Warn below 95%'
    UNION ALL
    SELECT 'Tables with >20% dead rows', (SELECT count(*)::text FROM admin.v_dead_tuples WHERE dead_pct > 20 AND dead_rows > 1000),
           CASE WHEN (SELECT count(*) FROM admin.v_dead_tuples WHERE dead_pct > 20 AND dead_rows > 1000) = 0 THEN 'OK' ELSE 'WARN' END,
           'Warn when a table over 1,000 dead rows is more than 20% dead'
    UNION ALL
    SELECT 'Last successful backup', coalesce((SELECT to_char(last_backup_at, 'YYYY-MM-DD HH24:MI') FROM admin.v_backup_status), 'never'),
           CASE WHEN (SELECT last_backup_at FROM admin.v_backup_status) > now() - interval '26 hours' THEN 'OK' ELSE 'FAIL' END,
           'Fail when older than 26 hours (daily schedule plus margin)'
    UNION ALL
    SELECT 'Last successful restore test', coalesce((SELECT to_char(last_restore_test_at, 'YYYY-MM-DD HH24:MI') FROM admin.v_backup_status), 'never'),
           CASE WHEN (SELECT last_restore_test_at FROM admin.v_backup_status) > now() - interval '8 days' THEN 'OK' ELSE 'WARN' END,
           'Warn when older than 8 days (weekly schedule)'
    UNION ALL
    SELECT 'Rows rejected on import (30 days)',
           (SELECT coalesce(sum(rows_rejected), 0)::text FROM staging.import_batches WHERE loaded_at > now() - interval '30 days'),
           CASE WHEN (SELECT coalesce(sum(rows_rejected), 0) FROM staging.import_batches WHERE loaded_at > now() - interval '30 days') = 0 THEN 'OK' ELSE 'WARN' END,
           'Warn when any row was rejected; see admin.v_failed_imports'
    UNION ALL
    SELECT 'Reporting refreshed', coalesce((SELECT to_char(max(finished_at), 'YYYY-MM-DD HH24:MI') FROM admin.job_runs WHERE job_name = 'refresh_reporting' AND status = 'SUCCESS'), 'never'),
           CASE WHEN (SELECT max(finished_at) FROM admin.job_runs WHERE job_name = 'refresh_reporting' AND status = 'SUCCESS') > now() - interval '26 hours' THEN 'OK' ELSE 'WARN' END,
           'Warn when older than 26 hours'
)
SELECT * FROM m;
COMMENT ON VIEW admin.v_health IS 'One row per health metric with its current value, status (OK, WARN, FAIL) and threshold.';

# Monitoring and data quality

## Health check

`admin.v_health` returns one row per metric with its value, a status (OK, WARN or FAIL) and the threshold.
`administration/monitoring/health_report.py` prints it as the `monitor` login, saves a JSON snapshot, and exits with
1 on FAIL and 2 on WARN so a scheduler or CI step can alert. The scheduler runs it every hour.

| Metric | Source | Threshold |
|---|---|---|
| Database size | `pg_database_size` | Warn above 5 GB |
| Active connections | `pg_stat_activity` | Warn above 80% of `max_connections` |
| Idle in transaction | `pg_stat_activity` | Warn on any session idle in a transaction for 5 minutes |
| Long-running queries | `pg_stat_activity` | Warn on any query over 30 s |
| Cache hit ratio | `pg_stat_database` | Warn below 95% |
| Tables with many dead rows | `pg_stat_user_tables` | Warn when a table over 1,000 dead rows is more than 20% dead |
| Last successful backup | `admin.backup_log` | Fail when older than 26 hours |
| Last successful restore test | `admin.backup_log` | Warn when older than 8 days |
| Rows rejected on import | `staging.import_batches` | Warn when any row was rejected in 30 days |
| Reporting refreshed | `admin.job_runs` | Warn when older than 26 hours |

Supporting views for investigation: `admin.v_table_sizes`, `admin.v_connections`, `admin.v_long_running_queries`,
`admin.v_index_usage` (with a flag for indexes never used), `admin.v_dead_tuples`, `admin.v_top_queries`
(`pg_stat_statements`), `admin.v_backup_status` and `admin.v_failed_imports`.

The `monitor` role reads these through PostgreSQL's predefined `pg_monitor` role and cannot read any asset data.

## Data quality

Every incoming row passes through `staging` and is checked against the rules in `staging.validation_rules` before
it can reach the register:

| Rule | Check |
|---|---|
| R01 | Asset type is missing or unknown |
| R02 | Status is unknown |
| R03 | Install date is not a valid YYYY-MM-DD date |
| R04 | Install date is in the future or before 1900 |
| R05 | No geometry given |
| R06 | Geometry cannot be read, is empty or invalid |
| R07 | Coordinates outside South Africa (usually longitude and latitude swapped) |
| R08 | Geometry type does not match the asset type |
| R09 | Asset outside the study area |
| R10 | Asset code repeated within the batch |
| R11 | Asset code already in the register |
| R12 | Asset code has the wrong format or prefix |
| R13 | Source feature already imported |
| R99 | Passed the rules but failed a database constraint on promotion (the message gives the detail) |

Every failure is kept in `staging.import_rejections`, one row per rule broken, so a supplier can be told exactly
what to fix. `data/incoming/sample_with_errors.csv` contains one row for each rule and is used by
`tests/test_staging.py`.

### Result of the demonstration load

12 batches, 11,889 rows. 11,879 were promoted. 10 were rejected under R09: road and stormwater pieces whose
representative point fell just outside the study area once the ward boundary had been simplified to 5 m. The
pipeline caught a genuine edge case in the source preparation rather than letting the pieces in with a wrong ward.

## Automation

| Job | Schedule | Script |
|---|---|---|
| Health report | Hourly | `administration/monitoring/health_report.py` |
| Refresh reporting | Daily 01:30 | `operations.refresh_reporting()` |
| Backup | Daily 02:00 | `administration/backup/backup.py` |
| Restore test | Sunday 03:00 | `administration/restore/restore_test.py` |
| Full rebuild, tests, backup and restore test | Every push and every Monday | `.github/workflows/ci.yml` |

Every job run is recorded in `admin.job_runs`.

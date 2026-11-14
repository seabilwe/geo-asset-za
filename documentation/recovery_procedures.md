# Backup and recovery procedures

## What is backed up

| File | Made with | Contains |
|---|---|---|
| `geoasset_za_<timestamp>.dump` | `pg_dump --format=custom` | Every schema, table, view, function, trigger, policy, grant and row |
| `globals_<timestamp>.sql` | `pg_dumpall --globals-only --no-role-passwords` | Roles and memberships (they live in the cluster, not the database) |

Each backup is logged in `admin.backup_log` with its size, SHA-256 checksum and the row count of every table.
The scheduler takes one every night at 02:00 and keeps the last seven.

**Recovery point objective:** up to 24 hours of changes (daily logical backups).
**Recovery time objective:** minutes. Restoring the demonstration database takes about 3 seconds.

## Routine: take a backup

```bash
python administration/backup/backup.py --dir backups --keep 7
# in Docker
docker compose exec scheduler python administration/backup/backup.py
```

## Routine: prove the backup works (weekly, and in CI on every push)

```bash
python administration/restore/restore_test.py
```

It restores the newest logged backup into a scratch database `geoasset_za_restore_test` and checks:

1. the file's SHA-256 matches the logged checksum
2. `pg_restore` finishes without errors
3. every table has the row count logged at backup time
4. the same number of tables, views, functions, triggers, indexes and policies exist
5. the schema version matches
6. geometries are valid and the GiST index is used
7. the API headline figures match the live database

The result is logged as `RESTORE_TEST` in `admin.backup_log`, written to
`administration/restore/reports/latest.md`, and shown in the health check. The latest result is in that report.

## Incident: restore the database on the same server

1. Stop writers: `docker compose stop api scheduler`.
2. Find the backup: `SELECT backup_id, finished_at, file_name, sha256 FROM admin.backup_log WHERE kind = 'BACKUP' AND status = 'SUCCESS' ORDER BY backup_id DESC;`
   (if the database is gone, use the newest file in `backups/`).
3. Check the file: `sha256sum backups/<file>.dump` and compare.
4. Restore under a new name first, never over the damaged database:
   ```bash
   createdb geoasset_za_restored
   pg_restore --exit-on-error --dbname geoasset_za_restored backups/<file>.dump
   ```
5. Verify: `python administration/restore/restore_test.py --file backups/<file>.dump --keep-db`, or run
   `SELECT * FROM api.kpis;` and spot checks.
6. Swap names during a short outage:
   ```sql
   ALTER DATABASE geoasset_za RENAME TO geoasset_za_damaged;
   ALTER DATABASE geoasset_za_restored RENAME TO geoasset_za;
   ```
7. Restart: `docker compose start api scheduler`. Keep `geoasset_za_damaged` until the cause is understood.

## Incident: restore on a new server

Roles are not inside the database dump, so they go first:

```bash
psql -f backups/globals_<timestamp>.sql postgres        # roles and memberships, without passwords
python administration/security/create_login_roles.py     # sets passwords from the environment
createdb geoasset_za
pg_restore --exit-on-error --dbname geoasset_za backups/<file>.dump
```

The new server needs PostgreSQL 16 or later with PostGIS 3.4 or later and `pg_stat_statements` in
`shared_preload_libraries`.

## Incident: recover a single table or a few rows

The custom format allows restoring one table into a scratch database and copying rows back:

```bash
createdb scratch && pg_restore --dbname scratch --schema-only backups/<file>.dump
pg_restore --dbname scratch --data-only --table work_orders backups/<file>.dump
```

For a single changed or deleted record, `audit.change_log` holds the previous values as JSON and is often faster
than a restore.

## Limits of this approach

A logical dump is one consistent moment. Changes after the last dump are lost, and a large database takes longer
to dump and restore than to copy. A production system would add physical backups with continuous WAL archiving
(`pg_basebackup` with `archive_command`, or a tool such as pgBackRest or Barman), which allow point-in-time
recovery to any second, and a streaming replica for fast failover. Logical dumps remain useful alongside them for
moving data between versions and for single-table recovery.

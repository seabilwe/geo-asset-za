# GEO-ASSET ZA

[![Database CI](https://github.com/seabilwe/geo-asset-za/actions/workflows/ci.yml/badge.svg)](https://github.com/seabilwe/geo-asset-za/actions/workflows/ci.yml)

**A municipal infrastructure asset register in PostgreSQL and PostGIS: designed, secured, tested, backed up,
monitored and published.**

GEO-ASSET ZA manages 11,879 infrastructure assets (roads, traffic signals, streetlights, water mains, hydrants,
stormwater, electricity network and community facilities) and their maintenance history in Hatfield, Hillcrest,
Brooklyn and part of Arcadia, City of Tshwane (wards 56, 82 and 92). The project is about the database: its
design, administration, security, performance and automation. The map and dashboard exist to show what the
database can do.

**Explore the map and dashboard:** [seabilwe.github.io/map-geo-asset-za.html](https://seabilwe.github.io/map-geo-asset-za.html)

> Locations come from OpenStreetMap and the Municipal Demarcation Board, with streetlight infill, water mains and
> hydrants generated along the real road network. **All condition, inspection, work order and cost data is
> synthetic** and describes no real asset. See [data/README.md](data/README.md).

## What it demonstrates

| Area | Evidence |
|---|---|
| Relational design | [Entity relationship diagram](documentation/erd.svg), [data dictionary](documentation/data_dictionary.md) and [architecture notes](documentation/database_architecture.md): supertype and detail tables, one geometry column checked by trigger, lookups as tables, no stored derived values |
| Data integrity | Constraints and triggers that reject invalid records; 26 tests in [`tests/test_integrity.py`](tests/test_integrity.py) |
| Versioned schema | 15 migrations with checksums in [`database/migrations`](database/migrations), applied by [`database/migrate.py`](database/migrate.py) |
| Security | Eight group roles, column privileges, row-level security, definer functions, read-only public views; [security notes](documentation/security.md), [privilege matrix](documentation/privilege_matrix.md), 16 tests |
| ETL and validation | Staging pipeline with 13 validation rules and a rejection log ([`staging`](database/migrations/V006__staging.sql), [`etl/import_assets.py`](etl/import_assets.py)) |
| Audit | Trigger-based change log with changed fields, written through a definer function |
| Backup and recovery | [Backup](administration/backup/backup.py), [automated restore test](administration/restore/restore_test.py) with seven checks, [runbook](documentation/recovery_procedures.md), [latest result](administration/restore/reports/latest.md) |
| Performance | GiST, KNN and clustering benchmarks on 2 million points with `EXPLAIN (ANALYZE, BUFFERS)`: [performance report](documentation/performance_report.md) |
| Monitoring | Health view with thresholds, monitoring role without data access: [monitoring and data quality](documentation/monitoring_and_data_quality.md) |
| Automation | Scheduler for backups, restore tests, refreshes and health checks; [GitHub Actions](.github/workflows/ci.yml) rebuilds, tests, backs up and restores on every push |
| Web integration | Read-only FastAPI service on the `api` views ([`api/`](api/)), and a static snapshot for the portfolio page |

## Run it

Needs Docker Desktop (or Docker Engine with Compose).

```bash
git clone https://github.com/seabilwe/geo-asset-za.git
cd geo-asset-za
cp .env.example .env            # then change the passwords in .env
docker compose up -d            # the first start builds the database: about a minute
```

| What | Where |
|---|---|
| Map and dashboard | http://localhost:8000 |
| API reference | http://localhost:8000/docs |
| Database (QGIS, psql, pgAdmin) | `localhost:5433`, database `geoasset_za`, a login from `create_login_roles.py`, password from `.env` |
| pgAdmin | `docker compose --profile admin up -d pgadmin`, then http://localhost:5050 |

Useful commands:

```bash
docker compose logs -f bootstrap                                         # watch the build
docker compose exec scheduler python administration/backup/backup.py     # back up now
docker compose exec scheduler python administration/restore/restore_test.py
docker compose exec scheduler python administration/monitoring/health_report.py
docker compose exec scheduler python -m pytest -q
```

Without Docker: PostgreSQL 16 with PostGIS 3.4 and `pg_stat_statements` preloaded, Python 3.11 or later,
`pip install -r requirements.txt`, set `PGHOST`, `PGUSER`, `PGPASSWORD` (a superuser) and run
`python etl/bootstrap.py`.

## Repository layout

```
database/
  migrations/          V001 to V015, the schema as versioned SQL
  seed_data/           reference lookups
  migrate.py           migration runner with checksums
etl/
  bootstrap.py         build the database from nothing
  import_assets.py     CSV -> staging -> validate -> promote
  generate_history.py  synthetic inspections, work orders and costs
  build_source_data.py OpenStreetMap + MDB -> data/ (maintainer step)
administration/
  security/            login roles
  backup/, restore/    backup, automated restore test, reports
  monitoring/          health report
  performance/         benchmark and results
  scheduler.py         routine jobs
api/                   FastAPI service on the api views
web/                   demonstration front-end and snapshot export
tests/                 integrity, security, staging and API tests
documentation/         architecture, ERD, data dictionary, security, recovery, performance, monitoring
data/                  source files and their licences
```

## Study area

Wards 56, 82 and 92 of the City of Tshwane (MDB 2026 boundaries), 28 km². Hatfield is split between wards 56
and 92; ward 82 adds Hillcrest and Brooklyn.

## Licence

Code and synthetic data: MIT. OpenStreetMap-derived data: ODbL 1.0, © OpenStreetMap contributors. Ward boundaries:
© Municipal Demarcation Board. Details in [data/README.md](data/README.md).

Built by [Seabilwe Tilodi](https://seabilwe.github.io).

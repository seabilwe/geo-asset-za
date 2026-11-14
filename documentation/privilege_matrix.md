# Privilege matrix

Generated from the catalog by `documentation/build_docs.py` with `has_table_privilege`, so it shows what each group role can actually do, including privileges inherited through membership. S = select, I = insert, U = update (u = some columns only), D = delete. Row-level security further limits `gaz_inspector` on `maintenance.inspections`.

| Object | admin | manager | inspector | analyst | etl | web | monitor |
|---|---|---|---|---|---|---|---|
| `reference.asset_classes` | SIUD | S | S | S | S | · | · |
| `reference.asset_statuses` | SIUD | S | S | S | S | · | · |
| `reference.asset_types` | SIUD | S | S | S | S | · | · |
| `reference.condition_grades` | SIUD | S | S | S | S | · | · |
| `reference.data_sources` | SIUD | S | S | S | S | · | · |
| `reference.defect_types` | SIUD | S | S | S | S | · | · |
| `reference.municipalities` | SIUD | S | S | S | S | · | · |
| `reference.wards` | SIUD | S | S | S | S | · | · |
| `reference.work_order_priorities` | SIUD | S | S | S | S | · | · |
| `assets.electrical_assets` | SIUD | SIUD | S | · | · | · | · |
| `assets.infrastructure_assets` | SIUD | SIU | Su | · | · | · | · |
| `assets.public_facilities` | SIUD | SIUD | S | · | · | · | · |
| `assets.road_segments` | SIUD | SIUD | S | · | · | · | · |
| `assets.stormwater_assets` | SIUD | SIUD | S | · | · | · | · |
| `assets.streetlights` | SIUD | SIUD | S | · | · | · | · |
| `assets.water_assets` | SIUD | SIUD | S | · | · | · | · |
| `maintenance.inspections` | SIUD | SIU | SIU | · | · | · | · |
| `maintenance.maintenance_activities` | SIUD | SIU | · | · | · | · | · |
| `maintenance.maintenance_costs` | SIUD | SIUD | · | · | · | · | · |
| `maintenance.work_orders` | SIUD | SIU | S | · | · | · | · |
| `operations.asset_condition_summary` | SIUD | S | · | S | · | · | · |
| `operations.maintenance_priority_summary` | SIUD | S | · | S | · | · | · |
| `operations.v_asset_register` | SIUD | S | · | S | · | · | · |
| `operations.v_latest_condition` | SIUD | S | · | S | · | · | · |
| `operations.v_maintenance_spend_monthly` | SIUD | S | · | S | · | · | · |
| `operations.v_work_order_performance` | SIUD | S | · | S | · | · | · |
| `audit.change_log` | SIUD | S | · | · | · | · | · |
| `staging.import_batches` | SIUD | S | · | · | SID | · | · |
| `staging.import_rejections` | SIUD | S | · | · | S | · | · |
| `staging.incoming_assets` | SIUD | S | · | · | SID | · | · |
| `staging.validation_rules` | SIUD | S | · | · | S | · | · |
| `api.asset_details` | SIUD | S | · | S | · | S | · |
| `api.asset_history` | SIUD | S | · | S | · | S | · |
| `api.assets` | SIUD | S | · | S | · | S | · |
| `api.kpis` | SIUD | S | · | S | · | S | · |
| `api.lookups` | SIUD | S | · | S | · | S | · |
| `api.priority_assets` | SIUD | S | · | S | · | S | · |
| `api.spend_by_month` | SIUD | S | · | S | · | S | · |
| `api.summary_by_type` | SIUD | S | · | S | · | S | · |
| `api.wards` | SIUD | S | · | S | · | S | · |
| `api.work_order_performance` | SIUD | S | · | S | · | S | · |
| `admin.backup_log` | SIUD | · | · | · | · | · | S |
| `admin.job_runs` | SIUD | · | · | · | · | · | S |
| `admin.schema_migrations` | SIUD | · | · | · | · | · | S |
| `admin.v_backup_status` | SIUD | · | · | · | · | · | S |
| `admin.v_cache_hit_ratio` | SIUD | · | · | · | · | · | S |
| `admin.v_connections` | SIUD | · | · | · | · | · | S |
| `admin.v_database_size` | SIUD | · | · | · | · | · | S |
| `admin.v_dead_tuples` | SIUD | · | · | · | · | · | S |
| `admin.v_failed_imports` | SIUD | · | · | · | · | · | S |
| `admin.v_health` | SIUD | · | · | · | · | · | S |
| `admin.v_index_usage` | SIUD | · | · | · | · | · | S |
| `admin.v_long_running_queries` | SIUD | · | · | · | · | · | S |
| `admin.v_table_sizes` | SIUD | · | · | · | · | · | S |
| `admin.v_top_queries` | SIUD | · | · | · | · | · | S |

## Functions (EXECUTE)

| Function | admin | manager | inspector | analyst | etl | web | monitor |
|---|---|---|---|---|---|---|---|
| `admin.apply_ownership()` | X | · | · | · | · | · | · |
| `audit.set_enabled(boolean)` | X | · | · | · | · | · | · |
| `operations.refresh_reporting()` | X | X | · | · | · | · | · |
| `staging.promote_batch(bigint)` | X | · | · | · | X | · | · |
| `staging.try_date(text)` | X | · | · | · | X | · | · |
| `staging.try_geom(text,text,text)` | X | · | · | · | X | · | · |
| `staging.validate_batch(bigint)` | X | · | · | · | X | · | · |

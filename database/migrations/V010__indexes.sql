-- V010  Indexes
-- PostgreSQL indexes primary keys and unique constraints automatically, but not foreign keys. Every foreign key
-- that is used to join or that is checked when a parent row is deleted gets an index here.

-- Spatial: GiST indexes for ST_Intersects, ST_DWithin and bounding-box (&&) searches.
CREATE INDEX infrastructure_assets_geom_gist ON assets.infrastructure_assets USING gist (geom);
CREATE INDEX wards_geom_gist                 ON reference.wards USING gist (geom);

-- Foreign keys on the register
CREATE INDEX infrastructure_assets_type_idx   ON assets.infrastructure_assets (type_code);
CREATE INDEX infrastructure_assets_ward_idx   ON assets.infrastructure_assets (ward_id);
CREATE INDEX infrastructure_assets_status_idx ON assets.infrastructure_assets (status_code);

-- Maintenance: the latest-condition view reads inspections by asset, newest first
CREATE INDEX inspections_asset_date_idx   ON maintenance.inspections (asset_id, inspected_on DESC, inspection_id DESC);
CREATE INDEX inspections_grade_idx        ON maintenance.inspections (condition_grade) WHERE condition_grade >= 4;
CREATE INDEX work_orders_asset_idx        ON maintenance.work_orders (asset_id);
CREATE INDEX work_orders_inspection_idx   ON maintenance.work_orders (inspection_id);
-- partial index: only open work orders are searched by status, and they are a small share of all work orders
CREATE INDEX work_orders_open_idx         ON maintenance.work_orders (target_date) WHERE status IN ('OPEN', 'SCHEDULED', 'IN_PROGRESS');
CREATE INDEX activities_work_order_idx    ON maintenance.maintenance_activities (work_order_id);
CREATE INDEX costs_work_order_idx         ON maintenance.maintenance_costs (work_order_id);
CREATE INDEX costs_date_idx               ON maintenance.maintenance_costs (cost_date, cost_status);

-- Lookups referenced from other lookups
CREATE INDEX asset_types_class_idx ON reference.asset_types (class_code);
CREATE INDEX wards_municipality_idx ON reference.wards (municipality_code);

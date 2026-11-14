# Data dictionary

Generated from the database catalog by `documentation/build_docs.py`. Row counts are from the demonstration build.

## Schema `reference`

### `reference.asset_classes`

Top level of the asset hierarchy, aligned with the municipal department responsible for the assets.

Rows: 7

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `class_code` (PK) | varchar(10) | no |  |  |
| `class_name` | varchar(80) | no |  |  |
| `department` | varchar(120) | no |  |  |
| `sort_order` | smallint | no | 0 |  |

Constraints:

- `asset_classes_class_name_key`: `UNIQUE (class_name)`

### `reference.asset_statuses`

Lifecycle status of an asset.

Rows: 4

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `status_code` (PK) | varchar(20) | no |  |  |
| `label` | varchar(40) | no |  |  |
| `is_in_service` | boolean | no |  |  |

Constraints:

- `asset_statuses_label_key`: `UNIQUE (label)`

### `reference.asset_types`

Asset types and their asset-management parameters. geom_type is enforced on every asset by a trigger.

Rows: 18

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `type_code` (PK) | varchar(30) | no |  |  |
| `type_name` | varchar(80) | no |  |  |
| `class_code` (FK) | varchar(10) | no |  |  |
| `geom_type` | varchar(15) | no |  | Geometry family that assets of this type must have. Multi-part geometries of the same family are accepted. |
| `detail_table` | varchar(63) | yes |  |  |
| `design_life_years` | smallint | no |  |  |
| `inspection_interval_months` | smallint | no |  |  |
| `criticality` | smallint | no |  | Consequence of failure, 1 (minor) to 5 (severe). Used with condition to rank maintenance priority. |
| `replacement_unit_cost_zar` | numeric(12,2) | no |  | Indicative replacement cost per cost_unit, in rand. Illustrative values for the demonstration, not tendered rates. |
| `cost_unit` | varchar(10) | no |  |  |
| `code_prefix` | varchar(6) | no |  | Prefix of the asset code, for example SL for streetlights (SL-000123). |

Foreign keys: `class_code` → `reference.asset_classes`

Constraints:

- `asset_types_cost_unit_check`: `CHECK (((cost_unit)::text = ANY ((ARRAY['each'::character varying, 'm'::character varying, 'm2'::character varying])::text[])))`
- `asset_types_criticality_check`: `CHECK (((criticality >= 1) AND (criticality <= 5)))`
- `asset_types_design_life_years_check`: `CHECK (((design_life_years >= 1) AND (design_life_years <= 150)))`
- `asset_types_geom_type_check`: `CHECK (((geom_type)::text = ANY ((ARRAY['POINT'::character varying, 'LINESTRING'::character varying, 'POLYGON'::character varying])::text[])))`
- `asset_types_inspection_interval_months_check`: `CHECK (((inspection_interval_months >= 1) AND (inspection_interval_months <= 120)))`
- `asset_types_replacement_unit_cost_zar_check`: `CHECK ((replacement_unit_cost_zar >= (0)::numeric))`
- `asset_types_code_prefix_key`: `UNIQUE (code_prefix)`
- `asset_types_type_name_key`: `UNIQUE (type_name)`

### `reference.condition_grades`

Five-point condition scale used in South African municipal asset management (1 very good to 5 very poor).

Rows: 5

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `grade` (PK) | smallint | no |  |  |
| `label` | varchar(20) | no |  |  |
| `description` | text | no |  |  |
| `colour_hex` | character(7) | no |  |  |

Constraints:

- `condition_grades_colour_hex_check`: `CHECK ((colour_hex ~ '^#[0-9A-F]{6}$'::text))`
- `condition_grades_grade_check`: `CHECK (((grade >= 1) AND (grade <= 5)))`
- `condition_grades_label_key`: `UNIQUE (label)`

### `reference.data_sources`

Where a record or geometry came from, and under which licence.

Rows: 3

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `source_code` (PK) | varchar(20) | no |  |  |
| `source_name` | varchar(120) | no |  |  |
| `licence` | varchar(120) | no |  |  |
| `url` | varchar(255) | yes |  |  |
| `is_synthetic` | boolean | no | false | True when the values were generated for the demonstration and do not describe real infrastructure. |

### `reference.defect_types`

Defects an inspector can record, grouped by asset class.

Rows: 32

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `defect_code` (PK) | varchar(20) | no |  |  |
| `class_code` (FK) | varchar(10) | no |  |  |
| `label` | varchar(80) | no |  |  |

Foreign keys: `class_code` → `reference.asset_classes`

Constraints:

- `defect_types_class_code_label_key`: `UNIQUE (class_code, label)`

### `reference.municipalities`

Municipalities as coded by the Municipal Demarcation Board (MDB). Category A is a metropolitan municipality.

Rows: 1

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `municipality_code` (PK) | varchar(10) | no |  |  |
| `municipality_name` | varchar(120) | no |  |  |
| `province` | varchar(60) | no |  |  |
| `category` | character(1) | no |  |  |

Constraints:

- `municipalities_category_check`: `CHECK ((category = ANY (ARRAY['A'::bpchar, 'B'::bpchar, 'C'::bpchar])))`

### `reference.wards`

MDB ward boundaries. Assets are assigned to a ward automatically from their location.

Rows: 107

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `ward_id` (PK) | varchar(12) | no |  | MDB WardID, for example 79900056 (City of Tshwane ward 56). |
| `municipality_code` (FK) | varchar(10) | no |  |  |
| `ward_no` | smallint | no |  |  |
| `in_study_area` | boolean | no | false | True for the wards covered by the demonstration register (Hatfield and surrounds). |
| `demarcation_year` | smallint | no |  |  |
| `source_code` (FK) | varchar(20) | no |  |  |
| `geom` | geometry(MultiPolygon) | no |  |  |

Foreign keys: `municipality_code` → `reference.municipalities`; `source_code` → `reference.data_sources`

Constraints:

- `wards_geom_valid`: `CHECK (st_isvalid(geom))`
- `wards_ward_no_check`: `CHECK ((ward_no > 0))`
- `wards_municipality_ward_uq`: `UNIQUE (municipality_code, ward_no)`

### `reference.work_order_priorities`

Work order priorities and their target response times.

Rows: 4

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `priority_code` (PK) | varchar(2) | no |  |  |
| `label` | varchar(30) | no |  |  |
| `response_days` | smallint | no |  |  |

Constraints:

- `work_order_priorities_response_days_check`: `CHECK ((response_days > 0))`
- `work_order_priorities_label_key`: `UNIQUE (label)`

## Schema `assets`

### `assets.electrical_assets`

Electrical network details: substations and overhead lines.

Rows: 15

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `asset_id` (PK) | bigint | no |  |  |
| `voltage_kv` | numeric(6,2) | no |  |  |
| `rating_kva` | integer | yes |  |  |

Foreign keys: `asset_id` → `assets.infrastructure_assets`

Constraints:

- `electrical_assets_rating_kva_check`: `CHECK ((rating_kva > 0))`
- `electrical_assets_voltage_kv_check`: `CHECK (((voltage_kv > (0)::numeric) AND (voltage_kv <= (400)::numeric)))`

Triggers: `audit_change` (after delete, insert, update); `detail_matches_type` (before insert, update)

### `assets.infrastructure_assets`

The asset register. One row per asset, whatever its type or geometry.

Rows: 11,879

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `asset_id` (PK) | bigint | no | identity |  |
| `asset_code` | varchar(20) | no |  | Business key shown to users, prefix from reference.asset_types plus a six-digit number. Filled in automatically when left empty. |
| `asset_name` | varchar(150) | yes |  |  |
| `type_code` (FK) | varchar(30) | no |  |  |
| `ward_id` (FK) | varchar(12) | no |  | Ward containing the asset. Set by trigger from the geometry; any value supplied is overwritten. |
| `status_code` (FK) | varchar(20) | no | 'ACTIVE'::character varying |  |
| `install_date` | date | yes |  |  |
| `decommission_date` | date | yes |  |  |
| `geometry_source_code` (FK) | varchar(20) | no |  | Source of the location: OpenStreetMap (real) or synthetic (generated along the real road network). |
| `attribute_source_code` (FK) | varchar(20) | no |  | Source of the descriptive attributes. Synthetic for every asset in the demonstration. |
| `source_ref` | varchar(60) | yes |  | Identifier in the source dataset, for example OpenStreetMap node/123456789. |
| `geom` | geometry(4326) | no |  | Location in WGS 84 (EPSG:4326). Point, line or polygon as required by the asset type. |
| `created_at` | timestamptz | no | now() |  |
| `created_by` | name | no | CURRENT_USER |  |
| `updated_at` | timestamptz | no | now() |  |
| `updated_by` | name | no | CURRENT_USER |  |

Foreign keys: `attribute_source_code` → `reference.data_sources`; `geometry_source_code` → `reference.data_sources`; `status_code` → `reference.asset_statuses`; `type_code` → `reference.asset_types`; `ward_id` → `reference.wards`

Constraints:

- `assets_code_format`: `CHECK (((asset_code)::text ~ '^[A-Z]{2,6}-[0-9]{6}$'::text))`
- `assets_decommission_after_install`: `CHECK (((decommission_date IS NULL) OR (install_date IS NULL) OR (decommission_date >= install_date)))`
- `assets_decommissioned_has_date`: `CHECK ((((status_code)::text = 'DECOMMISSIONED'::text) = (decommission_date IS NOT NULL)))`
- `assets_geom_valid`: `CHECK ((st_isvalid(geom) AND (NOT st_isempty(geom))))`
- `assets_install_range`: `CHECK (((install_date IS NULL) OR (install_date >= '1900-01-01'::date)))`
- `infrastructure_assets_asset_code_key`: `UNIQUE (asset_code)`

Triggers: `asset_before_write` (before insert, update); `audit_change` (after delete, insert, update)

### `assets.public_facilities`

Public facility details: parks, playgrounds, sports facilities, libraries, clinics and similar.

Rows: 127

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `asset_id` (PK) | bigint | no |  |  |
| `facility_use` | varchar(60) | no |  |  |
| `operator` | varchar(120) | no |  | Responsible operator. In the demonstration all facilities are assumed to be municipal. |
| `is_accessible` | boolean | no | false |  |
| `floor_area_m2` | numeric(10,1) | yes |  |  |

Foreign keys: `asset_id` → `assets.infrastructure_assets`

Constraints:

- `public_facilities_floor_area_m2_check`: `CHECK ((floor_area_m2 > (0)::numeric))`

Triggers: `audit_change` (after delete, insert, update); `detail_matches_type` (before insert, update)

### `assets.road_segments`

Road segment details. Length is not stored: it is derived from the geometry in views, so it can never disagree with it.

Rows: 2,391

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `asset_id` (PK) | bigint | no |  |  |
| `road_name` | varchar(120) | yes |  |  |
| `road_class` | varchar(20) | no |  |  |
| `surface_type` | varchar(20) | no |  |  |
| `lanes` | smallint | no |  |  |
| `width_m` | numeric(4,1) | no |  |  |
| `is_oneway` | boolean | no | false |  |

Foreign keys: `asset_id` → `assets.infrastructure_assets`

Constraints:

- `road_segments_lanes_check`: `CHECK (((lanes >= 1) AND (lanes <= 8)))`
- `road_segments_road_class_check`: `CHECK (((road_class)::text = ANY ((ARRAY['Primary'::character varying, 'Secondary'::character varying, 'Tertiary'::character varying, 'Local'::character varying, 'Residential'::character varying, 'Living street'::character varying])::text[])))`
- `road_segments_surface_type_check`: `CHECK (((surface_type)::text = ANY ((ARRAY['Asphalt'::character varying, 'Concrete'::character varying, 'Paving blocks'::character varying, 'Gravel'::character varying])::text[])))`
- `road_segments_width_m_check`: `CHECK (((width_m >= 2.5) AND (width_m <= (40)::numeric)))`

Triggers: `audit_change` (after delete, insert, update); `detail_matches_type` (before insert, update)

### `assets.stormwater_assets`

Stormwater details: culverts where watercourses pass under roads, and channels.

Rows: 96

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `asset_id` (PK) | bigint | no |  |  |
| `structure` | varchar(20) | no |  |  |
| `size_mm` | smallint | yes |  |  |
| `is_lined` | boolean | no | false |  |

Foreign keys: `asset_id` → `assets.infrastructure_assets`

Constraints:

- `stormwater_assets_size_mm_check`: `CHECK (((size_mm >= 100) AND (size_mm <= 10000)))`
- `stormwater_assets_structure_check`: `CHECK (((structure)::text = ANY ((ARRAY['Culvert'::character varying, 'Channel'::character varying, 'Kerb inlet'::character varying])::text[])))`

Triggers: `audit_change` (after delete, insert, update); `detail_matches_type` (before insert, update)

### `assets.streetlights`

Streetlight details. lamp_type: LED, HPS (high-pressure sodium), MH (metal halide) or CFL.

Rows: 5,586

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `asset_id` (PK) | bigint | no |  |  |
| `lamp_type` | varchar(10) | no |  |  |
| `wattage_w` | smallint | no |  |  |
| `pole_height_m` | numeric(4,1) | no |  |  |
| `pole_material` | varchar(12) | no |  |  |

Foreign keys: `asset_id` → `assets.infrastructure_assets`

Constraints:

- `streetlights_lamp_type_check`: `CHECK (((lamp_type)::text = ANY ((ARRAY['LED'::character varying, 'HPS'::character varying, 'MH'::character varying, 'CFL'::character varying])::text[])))`
- `streetlights_pole_height_m_check`: `CHECK (((pole_height_m >= (3)::numeric) AND (pole_height_m <= (20)::numeric)))`
- `streetlights_pole_material_check`: `CHECK (((pole_material)::text = ANY ((ARRAY['Steel'::character varying, 'Concrete'::character varying, 'Aluminium'::character varying, 'Wood'::character varying])::text[])))`
- `streetlights_wattage_w_check`: `CHECK (((wattage_w >= 5) AND (wattage_w <= 1000)))`

Triggers: `audit_change` (after delete, insert, update); `detail_matches_type` (before insert, update)

### `assets.water_assets`

Water mains, hydrants and storage. diameter_mm applies to mains and hydrant connections, capacity_kl to storage.

Rows: 3,552

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `asset_id` (PK) | bigint | no |  |  |
| `material` | varchar(20) | yes |  |  |
| `diameter_mm` | smallint | yes |  |  |
| `capacity_kl` | numeric(10,1) | yes |  |  |
| `pressure_zone` | varchar(40) | yes |  |  |

Foreign keys: `asset_id` → `assets.infrastructure_assets`

Constraints:

- `water_assets_capacity_kl_check`: `CHECK ((capacity_kl > (0)::numeric))`
- `water_assets_diameter_mm_check`: `CHECK (((diameter_mm >= 50) AND (diameter_mm <= 2000)))`
- `water_assets_material_check`: `CHECK (((material)::text = ANY ((ARRAY['uPVC'::character varying, 'HDPE'::character varying, 'Asbestos cement'::character varying, 'Steel'::character varying, 'Ductile iron'::character varying, 'Cast iron'::character varying, 'Concrete'::character varying])::text[])))`

Triggers: `audit_change` (after delete, insert, update); `detail_matches_type` (before insert, update)

## Schema `maintenance`

### `maintenance.inspections`

Condition assessments. Each records a condition grade (1-5) and, for grades 4 and 5, the defect found.

Rows: 81,873  ·  Row-level security: on

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `inspection_id` (PK) | bigint | no | identity |  |
| `asset_id` (FK) | bigint | no |  |  |
| `inspected_on` | date | no |  |  |
| `condition_grade` (FK) | smallint | no |  |  |
| `defect_code` (FK) | varchar(20) | yes |  |  |
| `action_required` | boolean | no | false |  |
| `inspector` | name | no | CURRENT_USER | Database role of the inspector. Row-level security lets inspectors edit only their own inspections. |
| `notes` | text | yes |  |  |
| `created_at` | timestamptz | no | now() |  |

Foreign keys: `asset_id` → `assets.infrastructure_assets`; `condition_grade` → `reference.condition_grades`; `defect_code` → `reference.defect_types`

Constraints:

- `inspections_defect_when_poor`: `CHECK (((condition_grade < 4) OR (defect_code IS NOT NULL)))`
- `inspections_one_per_day`: `UNIQUE (asset_id, inspected_on)`

Triggers: `audit_change` (after delete, insert, update); `inspection_before_write` (before insert, update)

### `maintenance.maintenance_activities`

Work done on a work order. An activity date must fall on or after the work order was raised.

Rows: 21,356

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `activity_id` (PK) | bigint | no | identity |  |
| `work_order_id` (FK) | bigint | no |  |  |
| `activity_type` | varchar(40) | no |  |  |
| `performed_on` | date | no |  |  |
| `labour_hours` | numeric(6,2) | no |  |  |
| `crew` | varchar(60) | yes |  |  |
| `notes` | text | yes |  |  |

Foreign keys: `work_order_id` → `maintenance.work_orders`

Constraints:

- `maintenance_activities_labour_hours_check`: `CHECK (((labour_hours > (0)::numeric) AND (labour_hours <= (500)::numeric)))`

Triggers: `activity_before_write` (before insert, update); `audit_change` (after delete, insert, update)

### `maintenance.maintenance_costs`

Planned (budgeted) and actual (incurred) costs per work order, in rand.

Rows: 67,597

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `cost_id` (PK) | bigint | no | identity |  |
| `work_order_id` (FK) | bigint | no |  |  |
| `cost_type` | varchar(12) | no |  |  |
| `cost_status` | varchar(8) | no |  |  |
| `amount_zar` | numeric(12,2) | no |  |  |
| `cost_date` | date | no |  |  |

Foreign keys: `work_order_id` → `maintenance.work_orders`

Constraints:

- `maintenance_costs_amount_zar_check`: `CHECK ((amount_zar > (0)::numeric))`
- `maintenance_costs_cost_status_check`: `CHECK (((cost_status)::text = ANY ((ARRAY['PLANNED'::character varying, 'ACTUAL'::character varying])::text[])))`
- `maintenance_costs_cost_type_check`: `CHECK (((cost_type)::text = ANY ((ARRAY['LABOUR'::character varying, 'MATERIALS'::character varying, 'EQUIPMENT'::character varying, 'CONTRACTOR'::character varying])::text[])))`

Triggers: `audit_change` (after delete, insert, update)

### `maintenance.work_orders`

Work orders raised against assets, from inspections or reported faults.

Rows: 17,263

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `work_order_id` (PK) | bigint | no | identity |  |
| `wo_number` | varchar(20) | no |  |  |
| `asset_id` (FK) | bigint | no |  |  |
| `inspection_id` (FK) | bigint | yes |  |  |
| `wo_type` | varchar(12) | no |  |  |
| `priority_code` (FK) | varchar(2) | no |  |  |
| `status` | varchar(12) | no | 'OPEN'::character varying |  |
| `raised_on` | date | no |  |  |
| `target_date` | date | no |  | Defaults to raised_on plus the response time of the priority. |
| `completed_on` | date | yes |  |  |
| `description` | text | no |  |  |
| `created_at` | timestamptz | no | now() |  |

Foreign keys: `asset_id` → `assets.infrastructure_assets`; `inspection_id` → `maintenance.inspections`; `priority_code` → `reference.work_order_priorities`

Constraints:

- `wo_completed_after_raised`: `CHECK (((completed_on IS NULL) OR (completed_on >= raised_on)))`
- `wo_completed_has_date`: `CHECK ((((status)::text = 'COMPLETED'::text) = (completed_on IS NOT NULL)))`
- `wo_number_format`: `CHECK (((wo_number)::text ~ '^WO-[0-9]{4}-[0-9]{6}$'::text))`
- `wo_target_after_raised`: `CHECK ((target_date >= raised_on))`
- `work_orders_status_check`: `CHECK (((status)::text = ANY ((ARRAY['OPEN'::character varying, 'SCHEDULED'::character varying, 'IN_PROGRESS'::character varying, 'COMPLETED'::character varying, 'CANCELLED'::character varying])::text[])))`
- `work_orders_wo_type_check`: `CHECK (((wo_type)::text = ANY ((ARRAY['PREVENTIVE'::character varying, 'CORRECTIVE'::character varying, 'EMERGENCY'::character varying, 'REPLACEMENT'::character varying])::text[])))`
- `work_orders_wo_number_key`: `UNIQUE (wo_number)`

Triggers: `audit_change` (after delete, insert, update); `work_order_before_write` (before insert, update)

## Schema `audit`

### `audit.change_log`

Append-only history of changes to the asset register and maintenance records.

Rows: 23,646

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `log_id` (PK) | bigint | no | identity |  |
| `changed_at` | timestamptz | no | clock_timestamp() |  |
| `transaction_id` | bigint | no | txid_current() |  |
| `db_user` | name | no |  | Role that made the change (current_user at the time). |
| `session_user_name` | name | no | SESSION_USER |  |
| `application` | text | yes | current_setting('application_name'::text, true) |  |
| `schema_name` | name | no |  |  |
| `table_name` | name | no |  |  |
| `operation` | varchar(6) | no |  |  |
| `row_key` | text | no |  |  |
| `changed_fields` | text[] | yes |  | For updates, the columns whose values changed. |
| `old_row` | jsonb | yes |  |  |
| `new_row` | jsonb | yes |  |  |

Constraints:

- `change_log_operation_check`: `CHECK (((operation)::text = ANY ((ARRAY['INSERT'::character varying, 'UPDATE'::character varying, 'DELETE'::character varying])::text[])))`

## Schema `staging`

### `staging.import_batches`

One row per incoming file, with its validation and promotion results.

Rows: 12

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `batch_id` (PK) | bigint | no | identity |  |
| `source_file` | varchar(255) | no |  |  |
| `geometry_source_code` (FK) | varchar(20) | no |  |  |
| `attribute_source_code` (FK) | varchar(20) | no |  |  |
| `loaded_by` | name | no | CURRENT_USER |  |
| `loaded_at` | timestamptz | no | now() |  |
| `status` | varchar(10) | no | 'LOADED'::character varying |  |
| `rows_total` | integer | no | 0 |  |
| `rows_valid` | integer | yes |  |  |
| `rows_rejected` | integer | yes |  |  |
| `rows_promoted` | integer | yes |  |  |
| `validated_at` | timestamptz | yes |  |  |
| `promoted_at` | timestamptz | yes |  |  |

Foreign keys: `attribute_source_code` → `reference.data_sources`; `geometry_source_code` → `reference.data_sources`

Constraints:

- `import_batches_status_check`: `CHECK (((status)::text = ANY ((ARRAY['LOADED'::character varying, 'VALIDATED'::character varying, 'PROMOTED'::character varying, 'FAILED'::character varying])::text[])))`

### `staging.import_rejections`

Rejection log: every rule each rejected row failed.

Rows: 10

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `rejection_id` (PK) | bigint | no | identity |  |
| `batch_id` (FK) | bigint | no |  |  |
| `row_no` | integer | no |  |  |
| `rule_code` (FK) | varchar(4) | no |  |  |
| `message` | text | no |  |  |
| `rejected_at` | timestamptz | no | now() |  |

Foreign keys: `batch_id` → `staging.import_batches`; `rule_code` → `staging.validation_rules`

### `staging.incoming_assets`

Raw incoming asset rows. Everything is text so that bad values can be loaded, reported and rejected, not lost.

Rows: 11,889

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `batch_id` (PK) | bigint | no |  |  |
| `row_no` (PK) | integer | no |  |  |
| `asset_code` | text | yes |  |  |
| `asset_name` | text | yes |  |  |
| `type_code` | text | yes |  |  |
| `status_code` | text | yes |  |  |
| `install_date` | text | yes |  |  |
| `wkt` | text | yes |  |  |
| `lon` | text | yes |  |  |
| `lat` | text | yes |  |  |
| `source_ref` | text | yes |  |  |
| `details` | jsonb | no | '{}'::jsonb | Detail-table attributes as JSON, for example {"lamp_type": "LED", "wattage_w": 60}. |
| `is_valid` | boolean | yes |  |  |
| `promoted_asset_id` | bigint | yes |  |  |

Foreign keys: `batch_id` → `staging.import_batches`

### `staging.validation_rules`

The checks applied to every incoming row before it can enter the register.

Rows: 14

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `rule_code` (PK) | varchar(4) | no |  |  |
| `description` | text | no |  |  |

## Schema `admin`

### `admin.backup_log`

Every backup and every restore test, written by administration/backup and administration/restore.

Rows: 0

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `backup_id` (PK) | bigint | no | identity |  |
| `kind` | varchar(12) | no |  |  |
| `started_at` | timestamptz | no |  |  |
| `finished_at` | timestamptz | yes |  |  |
| `status` | varchar(8) | no |  |  |
| `file_name` | varchar(255) | yes |  |  |
| `size_bytes` | bigint | yes |  |  |
| `sha256` | character(64) | yes |  |  |
| `details` | jsonb | no | '{}'::jsonb |  |

Constraints:

- `backup_finished_after_start`: `CHECK (((finished_at IS NULL) OR (finished_at >= started_at)))`
- `backup_log_kind_check`: `CHECK (((kind)::text = ANY ((ARRAY['BACKUP'::character varying, 'RESTORE_TEST'::character varying])::text[])))`
- `backup_log_size_bytes_check`: `CHECK ((size_bytes >= 0))`
- `backup_log_status_check`: `CHECK (((status)::text = ANY ((ARRAY['RUNNING'::character varying, 'SUCCESS'::character varying, 'FAILED'::character varying])::text[])))`

### `admin.job_runs`

Log of scheduled and automated jobs: imports, reporting refreshes, backups.

Rows: 2

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `run_id` (PK) | bigint | no | identity |  |
| `job_name` | varchar(60) | no |  |  |
| `started_at` | timestamptz | no | clock_timestamp() |  |
| `finished_at` | timestamptz | yes |  |  |
| `status` | varchar(8) | no | 'RUNNING'::character varying |  |
| `rows_affected` | bigint | yes |  |  |
| `message` | text | yes |  |  |

Constraints:

- `job_runs_status_check`: `CHECK (((status)::text = ANY ((ARRAY['RUNNING'::character varying, 'SUCCESS'::character varying, 'FAILED'::character varying])::text[])))`

### `admin.schema_migrations`

Migrations applied to this database, with the checksum of each file at the time.

Rows: 13

| Column | Type | Null | Default | Description |
|---|---|---|---|---|
| `version` (PK) | varchar(10) | no |  |  |
| `name` | varchar(200) | no |  |  |
| `checksum` | character(64) | no |  |  |
| `applied_at` | timestamptz | no | now() |  |
| `applied_by` | name | no | CURRENT_USER |  |
| `duration_ms` | integer | no |  |  |

## Views

| View | Kind | Description |
|---|---|---|
| `admin.v_backup_status` | view | Recovery readiness: age of the last good backup and last successful restore test. |
| `admin.v_cache_hit_ratio` | view | Share of block reads served from shared buffers. Below about 95% on a warm database suggests too little memory. |
| `admin.v_connections` | view | Connections by role and state. Many "idle in transaction" sessions point to an application bug. |
| `admin.v_database_size` | view |  |
| `admin.v_dead_tuples` | view | Dead row versions left by updates and deletes, and when each table was last vacuumed and analysed. |
| `admin.v_failed_imports` | view | Rejected rows per batch and rule. |
| `admin.v_health` | view | One row per health metric with its current value, status (OK, WARN, FAIL) and threshold. |
| `admin.v_index_usage` | view | Index scans since statistics were reset. Non-unique indexes never scanned are candidates for removal. |
| `admin.v_long_running_queries` | view | Statements running for more than 30 seconds. |
| `admin.v_table_sizes` | view | Size of each table and materialized view, including indexes and TOAST. |
| `admin.v_top_queries` | view | The 20 statements with the most total execution time (pg_stat_statements). |
| `api.asset_details` | view | Type-specific attributes of each asset as JSON, one column per asset family. |
| `api.asset_history` | view | Inspections and work orders per asset, newest first when ordered by event_date. No inspector names. |
| `api.assets` | view | Public asset list with latest condition. Coordinates rounded to about 10 cm. |
| `api.kpis` | view | Headline figures for the dashboard, one row. |
| `api.lookups` | view | Codes and labels used by the web application. |
| `api.spend_by_month` | view | Planned and actual maintenance spend per month and asset class. |
| `api.summary_by_type` | view | Asset counts, quantities and condition bands per asset type. |
| `api.wards` | view | Study area ward boundaries. |
| `operations.asset_condition_summary` | materialized view | Assets in service by type, ward and latest condition grade (0 means never inspected). |
| `operations.maintenance_priority_summary` | materialized view | Risk score per asset in service: condition x criticality, plus 2 past design life and 1 if an inspection is overdue. |
| `operations.v_asset_register` | view | The register with type, ward, latest condition, age, quantity (length, area or count) and replacement value. |
| `operations.v_latest_condition` | view | Most recent inspection of each asset. |
| `operations.v_maintenance_spend_monthly` | view | Planned and actual maintenance spend per month and asset class. |
| `operations.v_work_order_performance` | view | Completed work orders per class and priority: share finished by the target date and median days to complete. |

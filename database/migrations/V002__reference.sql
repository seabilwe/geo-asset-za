-- V002  Reference data: boundaries and lookups
-- Lookups are tables rather than enums or CHECK lists, so that a new asset type or status is a row insert,
-- not a schema change, and so that each code can carry its own attributes (design life, unit cost, response time).

CREATE TABLE reference.data_sources (
    source_code   varchar(20)  PRIMARY KEY,
    source_name   varchar(120) NOT NULL,
    licence       varchar(120) NOT NULL,
    url           varchar(255),
    is_synthetic  boolean      NOT NULL DEFAULT false
);
COMMENT ON TABLE  reference.data_sources IS 'Where a record or geometry came from, and under which licence.';
COMMENT ON COLUMN reference.data_sources.is_synthetic IS 'True when the values were generated for the demonstration and do not describe real infrastructure.';

CREATE TABLE reference.municipalities (
    municipality_code varchar(10)  PRIMARY KEY,
    municipality_name varchar(120) NOT NULL,
    province          varchar(60)  NOT NULL,
    category          char(1)      NOT NULL CHECK (category IN ('A', 'B', 'C'))
);
COMMENT ON TABLE reference.municipalities IS 'Municipalities as coded by the Municipal Demarcation Board (MDB). Category A is a metropolitan municipality.';

CREATE TABLE reference.wards (
    ward_id           varchar(12)  PRIMARY KEY,
    municipality_code varchar(10)  NOT NULL REFERENCES reference.municipalities,
    ward_no           smallint     NOT NULL CHECK (ward_no > 0),
    in_study_area     boolean      NOT NULL DEFAULT false,
    demarcation_year  smallint     NOT NULL,
    source_code       varchar(20)  NOT NULL REFERENCES reference.data_sources,
    geom              geometry(MultiPolygon, 4326) NOT NULL,
    CONSTRAINT wards_municipality_ward_uq UNIQUE (municipality_code, ward_no),
    CONSTRAINT wards_geom_valid CHECK (ST_IsValid(geom))
);
COMMENT ON TABLE  reference.wards IS 'MDB ward boundaries. Assets are assigned to a ward automatically from their location.';
COMMENT ON COLUMN reference.wards.ward_id IS 'MDB WardID, for example 79900056 (City of Tshwane ward 56).';
COMMENT ON COLUMN reference.wards.in_study_area IS 'True for the wards covered by the demonstration register (Hatfield and surrounds).';

CREATE TABLE reference.asset_classes (
    class_code  varchar(10)  PRIMARY KEY,
    class_name  varchar(80)  NOT NULL UNIQUE,
    department  varchar(120) NOT NULL,
    sort_order  smallint     NOT NULL DEFAULT 0
);
COMMENT ON TABLE reference.asset_classes IS 'Top level of the asset hierarchy, aligned with the municipal department responsible for the assets.';

CREATE TABLE reference.asset_types (
    type_code                  varchar(30)   PRIMARY KEY,
    type_name                  varchar(80)   NOT NULL UNIQUE,
    class_code                 varchar(10)   NOT NULL REFERENCES reference.asset_classes,
    geom_type                  varchar(15)   NOT NULL CHECK (geom_type IN ('POINT', 'LINESTRING', 'POLYGON')),
    detail_table               varchar(63),
    design_life_years          smallint      NOT NULL CHECK (design_life_years BETWEEN 1 AND 150),
    inspection_interval_months smallint      NOT NULL CHECK (inspection_interval_months BETWEEN 1 AND 120),
    criticality                smallint      NOT NULL CHECK (criticality BETWEEN 1 AND 5),
    replacement_unit_cost_zar  numeric(12,2) NOT NULL CHECK (replacement_unit_cost_zar >= 0),
    cost_unit                  varchar(10)   NOT NULL CHECK (cost_unit IN ('each', 'm', 'm2')),
    code_prefix                varchar(6)    NOT NULL UNIQUE
);
COMMENT ON TABLE  reference.asset_types IS 'Asset types and their asset-management parameters. geom_type is enforced on every asset by a trigger.';
COMMENT ON COLUMN reference.asset_types.geom_type IS 'Geometry family that assets of this type must have. Multi-part geometries of the same family are accepted.';
COMMENT ON COLUMN reference.asset_types.criticality IS 'Consequence of failure, 1 (minor) to 5 (severe). Used with condition to rank maintenance priority.';
COMMENT ON COLUMN reference.asset_types.replacement_unit_cost_zar IS 'Indicative replacement cost per cost_unit, in rand. Illustrative values for the demonstration, not tendered rates.';
COMMENT ON COLUMN reference.asset_types.code_prefix IS 'Prefix of the asset code, for example SL for streetlights (SL-000123).';

CREATE TABLE reference.condition_grades (
    grade        smallint    PRIMARY KEY CHECK (grade BETWEEN 1 AND 5),
    label        varchar(20) NOT NULL UNIQUE,
    description  text        NOT NULL,
    colour_hex   char(7)     NOT NULL CHECK (colour_hex ~ '^#[0-9A-F]{6}$')
);
COMMENT ON TABLE reference.condition_grades IS 'Five-point condition scale used in South African municipal asset management (1 very good to 5 very poor).';

CREATE TABLE reference.asset_statuses (
    status_code  varchar(20) PRIMARY KEY,
    label        varchar(40) NOT NULL UNIQUE,
    is_in_service boolean    NOT NULL
);
COMMENT ON TABLE reference.asset_statuses IS 'Lifecycle status of an asset.';

CREATE TABLE reference.work_order_priorities (
    priority_code  varchar(2)  PRIMARY KEY,
    label          varchar(30) NOT NULL UNIQUE,
    response_days  smallint    NOT NULL CHECK (response_days > 0)
);
COMMENT ON TABLE reference.work_order_priorities IS 'Work order priorities and their target response times.';

CREATE TABLE reference.defect_types (
    defect_code  varchar(20) PRIMARY KEY,
    class_code   varchar(10) NOT NULL REFERENCES reference.asset_classes,
    label        varchar(80) NOT NULL,
    UNIQUE (class_code, label)
);
COMMENT ON TABLE reference.defect_types IS 'Defects an inspector can record, grouped by asset class.';

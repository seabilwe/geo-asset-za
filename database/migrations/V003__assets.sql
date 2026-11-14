-- V003  The asset register
-- Design: one supertype table (assets.infrastructure_assets) holds what every asset has: identity, type, location,
-- status, dates and provenance. Family-specific attributes live in 1:1 detail tables keyed on asset_id.
-- A single geometry column of type Geometry is used, and a trigger checks it against reference.asset_types.geom_type,
-- so points, lines and polygons share one register, one spatial index and one set of maintenance tables.

CREATE SEQUENCE assets.asset_code_seq START 1;

CREATE TABLE assets.infrastructure_assets (
    asset_id               bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asset_code             varchar(20)  NOT NULL UNIQUE,
    asset_name             varchar(150),
    type_code              varchar(30)  NOT NULL REFERENCES reference.asset_types,
    ward_id                varchar(12)  NOT NULL REFERENCES reference.wards,
    status_code            varchar(20)  NOT NULL DEFAULT 'ACTIVE' REFERENCES reference.asset_statuses,
    install_date           date,
    decommission_date      date,
    geometry_source_code   varchar(20)  NOT NULL REFERENCES reference.data_sources,
    attribute_source_code  varchar(20)  NOT NULL REFERENCES reference.data_sources,
    source_ref             varchar(60),
    geom                   geometry(Geometry, 4326) NOT NULL,
    created_at             timestamptz  NOT NULL DEFAULT now(),
    created_by             name         NOT NULL DEFAULT current_user,
    updated_at             timestamptz  NOT NULL DEFAULT now(),
    updated_by             name         NOT NULL DEFAULT current_user,
    CONSTRAINT assets_code_format   CHECK (asset_code ~ '^[A-Z]{2,6}-[0-9]{6}$'),
    CONSTRAINT assets_geom_valid    CHECK (ST_IsValid(geom) AND NOT ST_IsEmpty(geom)),
    CONSTRAINT assets_install_range CHECK (install_date IS NULL OR install_date >= DATE '1900-01-01'),
    CONSTRAINT assets_decommission_after_install CHECK (decommission_date IS NULL OR install_date IS NULL OR decommission_date >= install_date),
    CONSTRAINT assets_decommissioned_has_date CHECK ((status_code = 'DECOMMISSIONED') = (decommission_date IS NOT NULL))
);
COMMENT ON TABLE  assets.infrastructure_assets IS 'The asset register. One row per asset, whatever its type or geometry.';
COMMENT ON COLUMN assets.infrastructure_assets.asset_code IS 'Business key shown to users, prefix from reference.asset_types plus a six-digit number. Filled in automatically when left empty.';
COMMENT ON COLUMN assets.infrastructure_assets.ward_id IS 'Ward containing the asset. Set by trigger from the geometry; any value supplied is overwritten.';
COMMENT ON COLUMN assets.infrastructure_assets.geometry_source_code IS 'Source of the location: OpenStreetMap (real) or synthetic (generated along the real road network).';
COMMENT ON COLUMN assets.infrastructure_assets.attribute_source_code IS 'Source of the descriptive attributes. Synthetic for every asset in the demonstration.';
COMMENT ON COLUMN assets.infrastructure_assets.source_ref IS 'Identifier in the source dataset, for example OpenStreetMap node/123456789.';
COMMENT ON COLUMN assets.infrastructure_assets.geom IS 'Location in WGS 84 (EPSG:4326). Point, line or polygon as required by the asset type.';

CREATE UNIQUE INDEX assets_source_ref_uq ON assets.infrastructure_assets (geometry_source_code, source_ref) WHERE source_ref IS NOT NULL;

-- Detail tables -------------------------------------------------------------------------------------------------

CREATE TABLE assets.streetlights (
    asset_id       bigint       PRIMARY KEY REFERENCES assets.infrastructure_assets ON DELETE CASCADE,
    lamp_type      varchar(10)  NOT NULL CHECK (lamp_type IN ('LED', 'HPS', 'MH', 'CFL')),
    wattage_w      smallint     NOT NULL CHECK (wattage_w BETWEEN 5 AND 1000),
    pole_height_m  numeric(4,1) NOT NULL CHECK (pole_height_m BETWEEN 3 AND 20),
    pole_material  varchar(12)  NOT NULL CHECK (pole_material IN ('Steel', 'Concrete', 'Aluminium', 'Wood'))
);
COMMENT ON TABLE assets.streetlights IS 'Streetlight details. lamp_type: LED, HPS (high-pressure sodium), MH (metal halide) or CFL.';

CREATE TABLE assets.road_segments (
    asset_id      bigint       PRIMARY KEY REFERENCES assets.infrastructure_assets ON DELETE CASCADE,
    road_name     varchar(120),
    road_class    varchar(20)  NOT NULL CHECK (road_class IN ('Primary', 'Secondary', 'Tertiary', 'Local', 'Residential', 'Living street')),
    surface_type  varchar(20)  NOT NULL CHECK (surface_type IN ('Asphalt', 'Concrete', 'Paving blocks', 'Gravel')),
    lanes         smallint     NOT NULL CHECK (lanes BETWEEN 1 AND 8),
    width_m       numeric(4,1) NOT NULL CHECK (width_m BETWEEN 2.5 AND 40),
    is_oneway     boolean      NOT NULL DEFAULT false
);
COMMENT ON TABLE assets.road_segments IS 'Road segment details. Length is not stored: it is derived from the geometry in views, so it can never disagree with it.';

CREATE TABLE assets.water_assets (
    asset_id       bigint        PRIMARY KEY REFERENCES assets.infrastructure_assets ON DELETE CASCADE,
    material       varchar(20)   CHECK (material IN ('uPVC', 'HDPE', 'Asbestos cement', 'Steel', 'Ductile iron', 'Cast iron', 'Concrete')),
    diameter_mm    smallint      CHECK (diameter_mm BETWEEN 50 AND 2000),
    capacity_kl    numeric(10,1) CHECK (capacity_kl > 0),
    pressure_zone  varchar(40)
);
COMMENT ON TABLE assets.water_assets IS 'Water mains, hydrants and storage. diameter_mm applies to mains and hydrant connections, capacity_kl to storage.';

CREATE TABLE assets.electrical_assets (
    asset_id    bigint        PRIMARY KEY REFERENCES assets.infrastructure_assets ON DELETE CASCADE,
    voltage_kv  numeric(6,2)  NOT NULL CHECK (voltage_kv > 0 AND voltage_kv <= 400),
    rating_kva  integer       CHECK (rating_kva > 0)
);
COMMENT ON TABLE assets.electrical_assets IS 'Electrical network details: substations and overhead lines.';

CREATE TABLE assets.stormwater_assets (
    asset_id   bigint       PRIMARY KEY REFERENCES assets.infrastructure_assets ON DELETE CASCADE,
    structure  varchar(20)  NOT NULL CHECK (structure IN ('Culvert', 'Channel', 'Kerb inlet')),
    size_mm    smallint     CHECK (size_mm BETWEEN 100 AND 10000),
    is_lined   boolean      NOT NULL DEFAULT false
);
COMMENT ON TABLE assets.stormwater_assets IS 'Stormwater details: culverts where watercourses pass under roads, and channels.';

CREATE TABLE assets.public_facilities (
    asset_id        bigint       PRIMARY KEY REFERENCES assets.infrastructure_assets ON DELETE CASCADE,
    facility_use    varchar(60)  NOT NULL,
    operator        varchar(120) NOT NULL,
    is_accessible   boolean      NOT NULL DEFAULT false,
    floor_area_m2   numeric(10,1) CHECK (floor_area_m2 > 0)
);
COMMENT ON TABLE  assets.public_facilities IS 'Public facility details: parks, playgrounds, sports facilities, libraries, clinics and similar.';
COMMENT ON COLUMN assets.public_facilities.operator IS 'Responsible operator. In the demonstration all facilities are assumed to be municipal.';

-- Triggers ------------------------------------------------------------------------------------------------------

CREATE FUNCTION assets.asset_before_write() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    t       reference.asset_types%ROWTYPE;
    family  text;
    w       reference.wards%ROWTYPE;
BEGIN
    SELECT * INTO t FROM reference.asset_types WHERE type_code = NEW.type_code;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown asset type %', NEW.type_code USING ERRCODE = 'foreign_key_violation';
    END IF;

    -- 1. geometry family must match the asset type
    family := CASE ST_GeometryType(NEW.geom)
                  WHEN 'ST_Point' THEN 'POINT' WHEN 'ST_MultiPoint' THEN 'POINT'
                  WHEN 'ST_LineString' THEN 'LINESTRING' WHEN 'ST_MultiLineString' THEN 'LINESTRING'
                  WHEN 'ST_Polygon' THEN 'POLYGON' WHEN 'ST_MultiPolygon' THEN 'POLYGON'
                  ELSE 'OTHER' END;
    IF family <> t.geom_type THEN
        RAISE EXCEPTION 'Asset type % needs a % geometry, got %', NEW.type_code, t.geom_type, ST_GeometryType(NEW.geom)
              USING ERRCODE = 'check_violation';
    END IF;

    -- 2. the asset must lie in a ward of the study area; the ward is assigned here, never typed in
    SELECT * INTO w FROM reference.wards
     WHERE ST_Intersects(geom, ST_PointOnSurface(NEW.geom))
     ORDER BY in_study_area DESC LIMIT 1;
    IF NOT FOUND OR NOT w.in_study_area THEN
        RAISE EXCEPTION 'Asset % lies outside the study area', coalesce(NEW.asset_code, '(new)') USING ERRCODE = 'check_violation';
    END IF;
    NEW.ward_id := w.ward_id;

    -- 3. dates that depend on today cannot be CHECK constraints (they must be immutable), so they are checked here
    IF NEW.install_date > current_date THEN
        RAISE EXCEPTION 'Install date % is in the future', NEW.install_date USING ERRCODE = 'check_violation';
    END IF;

    -- 4. asset code: generated when empty, and its prefix must match the asset type
    IF NEW.asset_code IS NULL THEN
        NEW.asset_code := t.code_prefix || '-' || lpad(nextval('assets.asset_code_seq')::text, 6, '0');
    ELSIF split_part(NEW.asset_code, '-', 1) <> t.code_prefix THEN
        RAISE EXCEPTION 'Asset code % does not match the prefix % for type %', NEW.asset_code, t.code_prefix, NEW.type_code
              USING ERRCODE = 'check_violation';
    END IF;

    -- 5. who changed it and when
    IF TG_OP = 'UPDATE' THEN
        NEW.created_at := OLD.created_at;
        NEW.created_by := OLD.created_by;
        NEW.updated_at := now();
        NEW.updated_by := current_user;
    END IF;
    RETURN NEW;
END $$;
COMMENT ON FUNCTION assets.asset_before_write() IS 'Validates geometry family and study area, assigns the ward, checks dates, generates asset codes and stamps updates.';

CREATE TRIGGER asset_before_write
    BEFORE INSERT OR UPDATE ON assets.infrastructure_assets
    FOR EACH ROW EXECUTE FUNCTION assets.asset_before_write();

-- A detail row may only belong to an asset whose type points at that detail table.
CREATE FUNCTION assets.detail_matches_type() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    expected text;
BEGIN
    SELECT t.detail_table INTO expected
      FROM assets.infrastructure_assets a JOIN reference.asset_types t USING (type_code)
     WHERE a.asset_id = NEW.asset_id;
    IF expected IS DISTINCT FROM TG_TABLE_NAME THEN
        RAISE EXCEPTION 'Asset % cannot have a row in %.%: its type uses %', NEW.asset_id, TG_TABLE_SCHEMA, TG_TABLE_NAME, coalesce(expected, 'no detail table')
              USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['streetlights', 'road_segments', 'water_assets', 'electrical_assets', 'stormwater_assets', 'public_facilities'] LOOP
        EXECUTE format('CREATE TRIGGER detail_matches_type BEFORE INSERT OR UPDATE OF asset_id ON assets.%I
                        FOR EACH ROW EXECUTE FUNCTION assets.detail_matches_type()', t);
    END LOOP;
END $$;

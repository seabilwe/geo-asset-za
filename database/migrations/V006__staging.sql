-- V006  Staging and validation
-- Incoming files land in staging.incoming_assets with every column as text, exactly as received.
-- staging.validate_batch() applies the rules in staging.validation_rules set by set and logs each failure in
-- staging.import_rejections. staging.promote_batch() then moves the rows that passed into the register,
-- one savepoint per row, so a row that still breaks a database constraint is rejected without stopping the batch.

CREATE TABLE staging.import_batches (
    batch_id        bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_file     varchar(255) NOT NULL,
    geometry_source_code  varchar(20) NOT NULL REFERENCES reference.data_sources,
    attribute_source_code varchar(20) NOT NULL REFERENCES reference.data_sources,
    loaded_by       name         NOT NULL DEFAULT current_user,
    loaded_at       timestamptz  NOT NULL DEFAULT now(),
    status          varchar(10)  NOT NULL DEFAULT 'LOADED' CHECK (status IN ('LOADED', 'VALIDATED', 'PROMOTED', 'FAILED')),
    rows_total      integer      NOT NULL DEFAULT 0,
    rows_valid      integer,
    rows_rejected   integer,
    rows_promoted   integer,
    validated_at    timestamptz,
    promoted_at     timestamptz
);
COMMENT ON TABLE staging.import_batches IS 'One row per incoming file, with its validation and promotion results.';

CREATE TABLE staging.incoming_assets (
    batch_id      bigint  NOT NULL REFERENCES staging.import_batches ON DELETE CASCADE,
    row_no        integer NOT NULL,
    asset_code    text,
    asset_name    text,
    type_code     text,
    status_code   text,
    install_date  text,
    wkt           text,
    lon           text,
    lat           text,
    source_ref    text,
    details       jsonb   NOT NULL DEFAULT '{}'::jsonb,
    is_valid      boolean,
    promoted_asset_id bigint,
    PRIMARY KEY (batch_id, row_no)
);
COMMENT ON TABLE  staging.incoming_assets IS 'Raw incoming asset rows. Everything is text so that bad values can be loaded, reported and rejected, not lost.';
COMMENT ON COLUMN staging.incoming_assets.details IS 'Detail-table attributes as JSON, for example {"lamp_type": "LED", "wattage_w": 60}.';

CREATE TABLE staging.validation_rules (
    rule_code    varchar(4)   PRIMARY KEY,
    description  text         NOT NULL
);
COMMENT ON TABLE staging.validation_rules IS 'The checks applied to every incoming row before it can enter the register.';

INSERT INTO staging.validation_rules VALUES
    ('R01', 'Asset type is missing or not in reference.asset_types'),
    ('R02', 'Status is not in reference.asset_statuses'),
    ('R03', 'Install date is not a valid date (expected YYYY-MM-DD)'),
    ('R04', 'Install date is in the future or before 1900'),
    ('R05', 'No geometry: neither WKT nor longitude and latitude given'),
    ('R06', 'Geometry cannot be read, is empty or is not valid'),
    ('R07', 'Coordinates are outside South Africa (often swapped longitude and latitude)'),
    ('R08', 'Geometry type does not match the asset type'),
    ('R09', 'Asset lies outside the study area wards'),
    ('R10', 'Asset code appears more than once in the batch'),
    ('R11', 'Asset code already exists in the register'),
    ('R12', 'Asset code has the wrong format or prefix for its type'),
    ('R13', 'Source reference already exists in the register'),
    ('R99', 'Rejected by a database constraint on promotion (message gives the detail)');

CREATE TABLE staging.import_rejections (
    rejection_id  bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id      bigint      NOT NULL REFERENCES staging.import_batches ON DELETE CASCADE,
    row_no        integer     NOT NULL,
    rule_code     varchar(4)  NOT NULL REFERENCES staging.validation_rules,
    message       text        NOT NULL,
    rejected_at   timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE staging.import_rejections IS 'Rejection log: every rule each rejected row failed.';
CREATE INDEX import_rejections_batch_idx ON staging.import_rejections (batch_id, row_no);

-- Safe conversions: return NULL instead of raising, so validation can report the problem.
CREATE FUNCTION staging.try_date(t text) RETURNS date
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    IF t IS NULL OR t !~ '^\d{4}-\d{2}-\d{2}$' THEN RETURN NULL; END IF;
    RETURN t::date;
EXCEPTION WHEN others THEN RETURN NULL;
END $$;

CREATE FUNCTION staging.try_geom(wkt text, lon text, lat text) RETURNS geometry
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE g geometry;
BEGIN
    IF wkt IS NOT NULL AND btrim(wkt) <> '' THEN
        g := ST_GeomFromText(wkt, 4326);
    ELSIF lon IS NOT NULL AND lat IS NOT NULL THEN
        g := ST_SetSRID(ST_MakePoint(lon::double precision, lat::double precision), 4326);
    END IF;
    IF g IS NULL OR ST_IsEmpty(g) OR NOT ST_IsValid(g) THEN RETURN NULL; END IF;
    RETURN g;
EXCEPTION WHEN others THEN RETURN NULL;
END $$;

CREATE FUNCTION staging.validate_batch(p_batch bigint)
RETURNS TABLE (rule_code varchar, rows_failed bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    DELETE FROM staging.import_rejections r WHERE r.batch_id = p_batch;

    DROP TABLE IF EXISTS _v;
    CREATE TEMP TABLE _v ON COMMIT DROP AS
    SELECT i.row_no, i.asset_code, i.type_code, i.status_code, i.source_ref, i.install_date,
           (i.wkt IS NULL OR btrim(i.wkt) = '') AND (i.lon IS NULL OR i.lat IS NULL) AS no_geom,
           staging.try_geom(i.wkt, i.lon, i.lat) AS g,
           staging.try_date(i.install_date) AS d,
           t.type_code AS known_type, t.geom_type, t.code_prefix
      FROM staging.incoming_assets i
      LEFT JOIN reference.asset_types t ON t.type_code = i.type_code
     WHERE i.batch_id = p_batch;

    INSERT INTO staging.import_rejections (batch_id, row_no, rule_code, message)
    SELECT p_batch, row_no, 'R01', format('Unknown asset type "%s"', coalesce(type_code, '')) FROM _v WHERE known_type IS NULL
    UNION ALL
    SELECT p_batch, row_no, 'R02', format('Unknown status "%s"', status_code) FROM _v
     WHERE status_code IS NOT NULL AND status_code NOT IN (SELECT s.status_code FROM reference.asset_statuses s)
    UNION ALL
    SELECT p_batch, row_no, 'R03', format('Install date "%s" is not a valid date', install_date) FROM _v
     WHERE install_date IS NOT NULL AND btrim(install_date) <> '' AND d IS NULL
    UNION ALL
    SELECT p_batch, row_no, 'R04', format('Install date %s is out of range', d) FROM _v WHERE d > current_date OR d < DATE '1900-01-01'
    UNION ALL
    SELECT p_batch, row_no, 'R05', 'No geometry supplied' FROM _v WHERE no_geom
    UNION ALL
    SELECT p_batch, row_no, 'R06', 'Geometry cannot be read or is invalid' FROM _v WHERE NOT no_geom AND g IS NULL
    UNION ALL
    SELECT p_batch, row_no, 'R07', format('Coordinates %s, %s are outside South Africa', round(ST_X(ST_PointOnSurface(g))::numeric, 4), round(ST_Y(ST_PointOnSurface(g))::numeric, 4))
      FROM _v WHERE g IS NOT NULL AND NOT ST_Intersects(g, ST_MakeEnvelope(16.3, -35.0, 33.0, -22.1, 4326))
    UNION ALL
    SELECT p_batch, row_no, 'R08', format('%s needs a %s, got %s', known_type, geom_type, ST_GeometryType(g)) FROM _v
     WHERE g IS NOT NULL AND known_type IS NOT NULL
       AND replace(replace(upper(ST_GeometryType(g)), 'ST_', ''), 'MULTI', '') <> geom_type
    UNION ALL
    SELECT p_batch, v.row_no, 'R09', 'Outside the study area' FROM _v v
     WHERE v.g IS NOT NULL AND ST_Intersects(v.g, ST_MakeEnvelope(16.3, -35.0, 33.0, -22.1, 4326))
       AND NOT EXISTS (SELECT 1 FROM reference.wards w WHERE w.in_study_area AND ST_Intersects(w.geom, ST_PointOnSurface(v.g)))
    UNION ALL
    SELECT p_batch, row_no, 'R10', format('Asset code %s appears %s times in the batch', asset_code, n)
      FROM (SELECT row_no, asset_code, count(*) OVER (PARTITION BY asset_code) n FROM _v WHERE asset_code IS NOT NULL) x WHERE n > 1
    UNION ALL
    SELECT p_batch, v.row_no, 'R11', format('Asset code %s already exists', v.asset_code) FROM _v v
      JOIN assets.infrastructure_assets a ON a.asset_code = v.asset_code
    UNION ALL
    SELECT p_batch, row_no, 'R12', format('Asset code "%s" should look like %s-000123', asset_code, code_prefix) FROM _v
     WHERE asset_code IS NOT NULL AND known_type IS NOT NULL AND asset_code !~ ('^' || code_prefix || '-[0-9]{6}$')
    UNION ALL
    SELECT p_batch, v.row_no, 'R13', format('Source reference %s already exists', v.source_ref) FROM _v v
      JOIN staging.import_batches b ON b.batch_id = p_batch
      JOIN assets.infrastructure_assets a ON a.source_ref = v.source_ref AND a.geometry_source_code = b.geometry_source_code;

    UPDATE staging.incoming_assets i
       SET is_valid = NOT EXISTS (SELECT 1 FROM staging.import_rejections r WHERE r.batch_id = p_batch AND r.row_no = i.row_no)
     WHERE i.batch_id = p_batch;

    UPDATE staging.import_batches b
       SET status = 'VALIDATED', validated_at = now(),
           rows_total = (SELECT count(*) FROM staging.incoming_assets i WHERE i.batch_id = p_batch),
           rows_valid = (SELECT count(*) FROM staging.incoming_assets i WHERE i.batch_id = p_batch AND i.is_valid),
           rows_rejected = (SELECT count(*) FROM staging.incoming_assets i WHERE i.batch_id = p_batch AND NOT i.is_valid)
     WHERE b.batch_id = p_batch;

    RETURN QUERY SELECT r.rule_code, count(*) FROM staging.import_rejections r WHERE r.batch_id = p_batch GROUP BY 1 ORDER BY 1;
END $$;
COMMENT ON FUNCTION staging.validate_batch(bigint) IS 'Applies every validation rule to a batch, logs failures and marks each row valid or not. Returns failures per rule.';

CREATE FUNCTION staging.promote_batch(p_batch bigint) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    b      staging.import_batches%ROWTYPE;
    r      record;
    new_id bigint;
    n_ok   integer := 0;
BEGIN
    SELECT * INTO b FROM staging.import_batches WHERE batch_id = p_batch FOR UPDATE;
    IF b.status <> 'VALIDATED' THEN
        RAISE EXCEPTION 'Batch % is %, it must be VALIDATED before promotion', p_batch, b.status;
    END IF;

    FOR r IN SELECT i.*, t.detail_table FROM staging.incoming_assets i JOIN reference.asset_types t USING (type_code)
              WHERE i.batch_id = p_batch AND i.is_valid ORDER BY i.row_no LOOP
        BEGIN   -- each row runs in its own subtransaction
            INSERT INTO assets.infrastructure_assets
                   (asset_code, asset_name, type_code, ward_id, status_code, install_date,
                    geometry_source_code, attribute_source_code, source_ref, geom)
            VALUES (r.asset_code, r.asset_name, r.type_code, NULL, coalesce(r.status_code, 'ACTIVE'), staging.try_date(r.install_date),
                    b.geometry_source_code, b.attribute_source_code, r.source_ref, staging.try_geom(r.wkt, r.lon, r.lat))
            RETURNING asset_id INTO new_id;
            IF r.detail_table IS NOT NULL THEN
                EXECUTE format('INSERT INTO assets.%I SELECT (jsonb_populate_record(NULL::assets.%I, $1)).*', r.detail_table, r.detail_table)
                  USING r.details || jsonb_build_object('asset_id', new_id);
            END IF;
            UPDATE staging.incoming_assets SET promoted_asset_id = new_id WHERE batch_id = p_batch AND row_no = r.row_no;
            n_ok := n_ok + 1;
        EXCEPTION WHEN others THEN
            INSERT INTO staging.import_rejections (batch_id, row_no, rule_code, message) VALUES (p_batch, r.row_no, 'R99', SQLERRM);
            UPDATE staging.incoming_assets SET is_valid = false WHERE batch_id = p_batch AND row_no = r.row_no;
        END;
    END LOOP;

    UPDATE staging.import_batches
       SET status = 'PROMOTED', promoted_at = now(), rows_promoted = n_ok,
           rows_valid = n_ok, rows_rejected = rows_total - n_ok
     WHERE batch_id = p_batch;
    RETURN n_ok;
END $$;
COMMENT ON FUNCTION staging.promote_batch(bigint) IS 'Moves the valid rows of a validated batch into the register and detail tables. Rows that fail a constraint are logged as R99.';

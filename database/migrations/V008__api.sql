-- V008  Public API views
-- The public web application reads only these views. They expose no user names, no internal ids beyond the
-- asset code, no audit data and no decommissioned assets. security_barrier stops a caller's own functions in a
-- WHERE clause from seeing rows the view would filter out.

CREATE VIEW api.assets WITH (security_barrier) AS
SELECT r.asset_code, r.asset_name, r.class_code, r.class_name, r.type_code, r.type_name, r.ward_no,
       r.status_label AS status, extract(year FROM r.install_date)::int AS install_year, r.age_years,
       r.condition_grade, r.condition_label, r.last_inspected_on, r.inspection_overdue,
       r.quantity, r.cost_unit, r.replacement_value_zar,
       gs.source_name AS location_source, (asrc.is_synthetic) AS attributes_synthetic,
       ST_ReducePrecision(r.geom, 0.000001) AS geom
  FROM operations.v_asset_register r
  JOIN reference.data_sources gs ON gs.source_code = r.geometry_source_code
  JOIN reference.data_sources asrc ON asrc.source_code = r.attribute_source_code
 WHERE r.status_code <> 'DECOMMISSIONED';
COMMENT ON VIEW api.assets IS 'Public asset list with latest condition. Coordinates rounded to about 10 cm.';

CREATE VIEW api.asset_details WITH (security_barrier) AS
SELECT a.asset_code,
       to_jsonb(sl) - 'asset_id' AS streetlight,
       to_jsonb(rs) - 'asset_id' AS road,
       to_jsonb(wa) - 'asset_id' AS water,
       to_jsonb(ea) - 'asset_id' AS electrical,
       to_jsonb(sw) - 'asset_id' AS stormwater,
       to_jsonb(pf) - 'asset_id' AS facility
  FROM assets.infrastructure_assets a
  LEFT JOIN assets.streetlights sl USING (asset_id)
  LEFT JOIN assets.road_segments rs USING (asset_id)
  LEFT JOIN assets.water_assets wa USING (asset_id)
  LEFT JOIN assets.electrical_assets ea USING (asset_id)
  LEFT JOIN assets.stormwater_assets sw USING (asset_id)
  LEFT JOIN assets.public_facilities pf USING (asset_id)
 WHERE a.status_code <> 'DECOMMISSIONED';
COMMENT ON VIEW api.asset_details IS 'Type-specific attributes of each asset as JSON, one column per asset family.';

CREATE VIEW api.asset_history WITH (security_barrier) AS
SELECT a.asset_code, 'INSPECTION'::text AS event, i.inspected_on AS event_date,
       format('Condition %s (%s)', g.grade, g.label) AS summary, d.label AS detail, NULL::text AS status, NULL::numeric AS actual_cost_zar
  FROM maintenance.inspections i
  JOIN assets.infrastructure_assets a USING (asset_id)
  JOIN reference.condition_grades g ON g.grade = i.condition_grade
  LEFT JOIN reference.defect_types d USING (defect_code)
 WHERE a.status_code <> 'DECOMMISSIONED'
UNION ALL
SELECT a.asset_code, 'WORK ORDER', wo.raised_on,
       format('%s %s, %s priority', wo.wo_number, lower(wo.wo_type), p.label), wo.description, lower(wo.status),
       (SELECT sum(amount_zar) FROM maintenance.maintenance_costs mc WHERE mc.work_order_id = wo.work_order_id AND mc.cost_status = 'ACTUAL')
  FROM maintenance.work_orders wo
  JOIN assets.infrastructure_assets a USING (asset_id)
  JOIN reference.work_order_priorities p USING (priority_code)
 WHERE a.status_code <> 'DECOMMISSIONED';
COMMENT ON VIEW api.asset_history IS 'Inspections and work orders per asset, newest first when ordered by event_date. No inspector names.';

CREATE VIEW api.kpis AS
WITH reg AS (SELECT * FROM operations.v_asset_register WHERE status_code <> 'DECOMMISSIONED'),
     open_wo AS (SELECT DISTINCT asset_id FROM maintenance.work_orders WHERE status IN ('OPEN', 'SCHEDULED', 'IN_PROGRESS'))
SELECT (SELECT count(*) FROM reg) AS total_assets,
       (SELECT count(*) FROM reg WHERE condition_grade >= 4 OR asset_id IN (SELECT asset_id FROM open_wo)) AS assets_needing_maintenance,
       (SELECT count(*) FROM reg WHERE inspection_overdue) AS inspections_overdue,
       (SELECT jsonb_object_agg(coalesce(condition_label, 'Not inspected'), n) FROM
            (SELECT condition_label, count(*) n FROM reg GROUP BY 1) x) AS assets_by_condition,
       (SELECT count(*) FROM maintenance.work_orders WHERE status IN ('OPEN', 'SCHEDULED', 'IN_PROGRESS')) AS open_work_orders,
       (SELECT coalesce(sum(amount_zar), 0) FROM maintenance.maintenance_costs
         WHERE cost_status = 'ACTUAL' AND cost_date > current_date - interval '12 months') AS actual_spend_12m_zar,
       (SELECT coalesce(sum(mc.amount_zar), 0) FROM maintenance.maintenance_costs mc
          JOIN maintenance.work_orders wo USING (work_order_id)
         WHERE mc.cost_status = 'PLANNED' AND wo.status IN ('OPEN', 'SCHEDULED', 'IN_PROGRESS')) AS planned_spend_open_zar,
       (SELECT sum(replacement_value_zar) FROM reg) AS replacement_value_zar,
       (SELECT max(inspected_on) FROM maintenance.inspections) AS data_as_of;
COMMENT ON VIEW api.kpis IS 'Headline figures for the dashboard, one row.';

CREATE VIEW api.summary_by_type AS
SELECT class_code, class_name, type_code, type_name, cost_unit,
       count(*) AS assets, round(sum(quantity)) AS quantity,
       count(*) FILTER (WHERE condition_grade <= 2) AS good,
       count(*) FILTER (WHERE condition_grade = 3)  AS fair,
       count(*) FILTER (WHERE condition_grade >= 4) AS poor,
       count(*) FILTER (WHERE condition_grade IS NULL) AS not_inspected,
       round(sum(replacement_value_zar)) AS replacement_value_zar
  FROM operations.v_asset_register
 WHERE status_code <> 'DECOMMISSIONED'
 GROUP BY 1, 2, 3, 4, 5;
COMMENT ON VIEW api.summary_by_type IS 'Asset counts, quantities and condition bands per asset type.';

CREATE VIEW api.spend_by_month AS
SELECT month, class_code, cost_status, amount_zar FROM operations.v_maintenance_spend_monthly;
COMMENT ON VIEW api.spend_by_month IS 'Planned and actual maintenance spend per month and asset class.';

CREATE VIEW api.wards AS
SELECT ward_no, ward_id, ST_ReducePrecision(geom, 0.00001) AS geom FROM reference.wards WHERE in_study_area;
COMMENT ON VIEW api.wards IS 'Study area ward boundaries.';

CREATE VIEW api.lookups AS
SELECT 'condition' AS lookup, grade::text AS code, label, colour_hex AS extra FROM reference.condition_grades
UNION ALL SELECT 'class', class_code, class_name, department FROM reference.asset_classes
UNION ALL SELECT 'type', type_code, type_name, class_code FROM reference.asset_types;
COMMENT ON VIEW api.lookups IS 'Codes and labels used by the web application.';

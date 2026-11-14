-- V007  Operational reporting
-- Views answer the everyday questions; the two heavier summaries are materialized views with unique indexes,
-- so they can be refreshed CONCURRENTLY (readers are never blocked) by operations.refresh_reporting() in V009.

CREATE VIEW operations.v_latest_condition AS
SELECT DISTINCT ON (i.asset_id)
       i.asset_id, i.inspection_id, i.inspected_on, i.condition_grade, i.defect_code, i.action_required
  FROM maintenance.inspections i
 ORDER BY i.asset_id, i.inspected_on DESC, i.inspection_id DESC;
COMMENT ON VIEW operations.v_latest_condition IS 'Most recent inspection of each asset.';

CREATE VIEW operations.v_asset_register AS
SELECT a.asset_id, a.asset_code, a.asset_name,
       c.class_code, c.class_name, t.type_code, t.type_name,
       w.ward_no, a.ward_id, a.status_code, s.label AS status_label, s.is_in_service,
       a.install_date,
       date_part('year', age(current_date, a.install_date))::int AS age_years,
       t.design_life_years,
       round((date_part('year', age(current_date, a.install_date)) / t.design_life_years * 100)::numeric, 0) AS life_used_pct,
       lc.condition_grade, g.label AS condition_label, lc.inspected_on AS last_inspected_on,
       (lc.inspected_on IS NULL OR lc.inspected_on + make_interval(months => t.inspection_interval_months) < current_date) AS inspection_overdue,
       CASE t.cost_unit WHEN 'm'  THEN round(ST_Length(a.geom::geography)::numeric, 1)
                        WHEN 'm2' THEN round(ST_Area(a.geom::geography)::numeric, 1)
                        ELSE 1 END AS quantity,
       t.cost_unit,
       round(CASE t.cost_unit WHEN 'm'  THEN ST_Length(a.geom::geography)
                              WHEN 'm2' THEN ST_Area(a.geom::geography)
                              ELSE 1 END::numeric * t.replacement_unit_cost_zar, 2) AS replacement_value_zar,
       t.criticality,
       a.geometry_source_code, a.attribute_source_code, a.source_ref, a.geom
  FROM assets.infrastructure_assets a
  JOIN reference.asset_types t USING (type_code)
  JOIN reference.asset_classes c USING (class_code)
  JOIN reference.wards w USING (ward_id)
  JOIN reference.asset_statuses s USING (status_code)
  LEFT JOIN operations.v_latest_condition lc USING (asset_id)
  LEFT JOIN reference.condition_grades g ON g.grade = lc.condition_grade;
COMMENT ON VIEW operations.v_asset_register IS 'The register with type, ward, latest condition, age, quantity (length, area or count) and replacement value.';

CREATE MATERIALIZED VIEW operations.asset_condition_summary AS
SELECT class_code, class_name, type_code, type_name, ward_no,
       coalesce(condition_grade, 0) AS condition_grade,
       count(*)                     AS assets,
       sum(quantity)                AS quantity,
       sum(replacement_value_zar)   AS replacement_value_zar
  FROM operations.v_asset_register
 WHERE is_in_service
 GROUP BY class_code, class_name, type_code, type_name, ward_no, coalesce(condition_grade, 0)
WITH DATA;
CREATE UNIQUE INDEX asset_condition_summary_uq ON operations.asset_condition_summary (type_code, ward_no, condition_grade);
COMMENT ON MATERIALIZED VIEW operations.asset_condition_summary IS 'Assets in service by type, ward and latest condition grade (0 means never inspected).';

CREATE MATERIALIZED VIEW operations.maintenance_priority_summary AS
WITH open_wo AS (
    SELECT asset_id, count(*) AS open_work_orders, min(target_date) AS earliest_target
      FROM maintenance.work_orders
     WHERE status IN ('OPEN', 'SCHEDULED', 'IN_PROGRESS')
     GROUP BY asset_id
)
SELECT r.asset_id, r.asset_code, r.class_name, r.type_name, r.ward_no,
       r.condition_grade, r.criticality, r.life_used_pct, r.inspection_overdue,
       coalesce(o.open_work_orders, 0) AS open_work_orders, o.earliest_target,
       -- risk = likelihood (condition) x consequence (criticality), nudged up when past design life or overdue for inspection
       (coalesce(r.condition_grade, 3) * r.criticality
        + CASE WHEN r.life_used_pct >= 100 THEN 2 ELSE 0 END
        + CASE WHEN r.inspection_overdue THEN 1 ELSE 0 END) AS risk_score,
       r.replacement_value_zar
  FROM operations.v_asset_register r
  LEFT JOIN open_wo o USING (asset_id)
 WHERE r.is_in_service
WITH DATA;
CREATE UNIQUE INDEX maintenance_priority_summary_uq ON operations.maintenance_priority_summary (asset_id);
CREATE INDEX maintenance_priority_summary_risk_idx ON operations.maintenance_priority_summary (risk_score DESC);
COMMENT ON MATERIALIZED VIEW operations.maintenance_priority_summary IS 'Risk score per asset in service: condition x criticality, plus 2 past design life and 1 if an inspection is overdue.';

CREATE VIEW operations.v_maintenance_spend_monthly AS
SELECT date_trunc('month', mc.cost_date)::date AS month, t.class_code, mc.cost_status,
       sum(mc.amount_zar) AS amount_zar, count(DISTINCT mc.work_order_id) AS work_orders
  FROM maintenance.maintenance_costs mc
  JOIN maintenance.work_orders wo USING (work_order_id)
  JOIN assets.infrastructure_assets a USING (asset_id)
  JOIN reference.asset_types t USING (type_code)
 GROUP BY 1, 2, 3;
COMMENT ON VIEW operations.v_maintenance_spend_monthly IS 'Planned and actual maintenance spend per month and asset class.';

CREATE VIEW operations.v_work_order_performance AS
SELECT t.class_code, wo.priority_code, count(*) AS completed,
       round(avg((wo.completed_on <= wo.target_date)::int) * 100, 1) AS on_time_pct,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY wo.completed_on - wo.raised_on) AS median_days
  FROM maintenance.work_orders wo
  JOIN assets.infrastructure_assets a USING (asset_id)
  JOIN reference.asset_types t USING (type_code)
 WHERE wo.status = 'COMPLETED'
 GROUP BY 1, 2;
COMMENT ON VIEW operations.v_work_order_performance IS 'Completed work orders per class and priority: share finished by the target date and median days to complete.';

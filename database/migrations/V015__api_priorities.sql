-- V015  Two more views for the public dashboard: maintenance priorities and work order performance.
-- Objects created by a migration are owned by the migrating superuser until admin.apply_ownership() runs, so
-- default privileges (which apply to objects created by gaz_owner) do not cover them: grants are explicit.

CREATE VIEW api.priority_assets WITH (security_barrier) AS
SELECT p.asset_code, a.asset_name, p.class_name, p.type_name, p.ward_no, p.condition_grade, g.label AS condition_label,
       p.criticality, p.risk_score, p.life_used_pct, p.inspection_overdue, p.open_work_orders, p.earliest_target
  FROM operations.maintenance_priority_summary p
  JOIN assets.infrastructure_assets a USING (asset_id)
  LEFT JOIN reference.condition_grades g ON g.grade = p.condition_grade
 ORDER BY p.risk_score DESC, p.criticality DESC, p.asset_code;
COMMENT ON VIEW api.priority_assets IS 'Assets in service ranked by risk score (condition x criticality, adjusted for age and overdue inspection).';

CREATE VIEW api.work_order_performance AS
SELECT c.class_name, p.label AS priority, p.response_days, w.completed, w.on_time_pct, w.median_days
  FROM operations.v_work_order_performance w
  JOIN reference.asset_classes c USING (class_code)
  JOIN reference.work_order_priorities p USING (priority_code);
COMMENT ON VIEW api.work_order_performance IS 'Completed work orders per class and priority: share on time and median days to complete.';

GRANT SELECT ON api.priority_assets, api.work_order_performance TO gaz_web, gaz_analyst, gaz_manager;

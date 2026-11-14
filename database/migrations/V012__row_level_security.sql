-- V012  Row-level security on inspections
-- Inspectors see every inspection (they need an asset's history) but can only add inspections in their own name
-- and only edit their own. Managers have full access. The owner bypasses RLS as table owner.

ALTER TABLE maintenance.inspections ENABLE ROW LEVEL SECURITY;

CREATE POLICY inspections_manager_all ON maintenance.inspections
    FOR ALL TO gaz_manager USING (true) WITH CHECK (true);

CREATE POLICY inspections_inspector_read ON maintenance.inspections
    FOR SELECT TO gaz_inspector USING (true);

CREATE POLICY inspections_inspector_insert ON maintenance.inspections
    FOR INSERT TO gaz_inspector WITH CHECK (inspector = current_user);

CREATE POLICY inspections_inspector_update ON maintenance.inspections
    FOR UPDATE TO gaz_inspector USING (inspector = current_user) WITH CHECK (inspector = current_user);

COMMENT ON POLICY inspections_inspector_insert ON maintenance.inspections IS 'An inspector can only record inspections under their own login.';
COMMENT ON POLICY inspections_inspector_update ON maintenance.inspections IS 'An inspector can only edit inspections they recorded.';

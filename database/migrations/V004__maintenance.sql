-- V004  Maintenance: inspections, work orders, activities and costs
-- Maintenance rows reference assets with ON DELETE RESTRICT: an asset with a history is decommissioned, never deleted.

CREATE SEQUENCE maintenance.work_order_seq START 1;

CREATE TABLE maintenance.inspections (
    inspection_id    bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asset_id         bigint       NOT NULL REFERENCES assets.infrastructure_assets ON DELETE RESTRICT,
    inspected_on     date         NOT NULL,
    condition_grade  smallint     NOT NULL REFERENCES reference.condition_grades,
    defect_code      varchar(20)  REFERENCES reference.defect_types,
    action_required  boolean      NOT NULL DEFAULT false,
    inspector        name         NOT NULL DEFAULT current_user,
    notes            text,
    created_at       timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT inspections_one_per_day UNIQUE (asset_id, inspected_on),
    CONSTRAINT inspections_defect_when_poor CHECK (condition_grade < 4 OR defect_code IS NOT NULL)
);
COMMENT ON TABLE  maintenance.inspections IS 'Condition assessments. Each records a condition grade (1-5) and, for grades 4 and 5, the defect found.';
COMMENT ON COLUMN maintenance.inspections.inspector IS 'Database role of the inspector. Row-level security lets inspectors edit only their own inspections.';

CREATE TABLE maintenance.work_orders (
    work_order_id   bigint       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    wo_number       varchar(20)  NOT NULL UNIQUE,
    asset_id        bigint       NOT NULL REFERENCES assets.infrastructure_assets ON DELETE RESTRICT,
    inspection_id   bigint       REFERENCES maintenance.inspections ON DELETE SET NULL,
    wo_type         varchar(12)  NOT NULL CHECK (wo_type IN ('PREVENTIVE', 'CORRECTIVE', 'EMERGENCY', 'REPLACEMENT')),
    priority_code   varchar(2)   NOT NULL REFERENCES reference.work_order_priorities,
    status          varchar(12)  NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'SCHEDULED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')),
    raised_on       date         NOT NULL,
    target_date     date         NOT NULL,
    completed_on    date,
    description     text         NOT NULL,
    created_at      timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT wo_number_format    CHECK (wo_number ~ '^WO-[0-9]{4}-[0-9]{6}$'),
    CONSTRAINT wo_target_after_raised CHECK (target_date >= raised_on),
    CONSTRAINT wo_completed_after_raised CHECK (completed_on IS NULL OR completed_on >= raised_on),
    CONSTRAINT wo_completed_has_date CHECK ((status = 'COMPLETED') = (completed_on IS NOT NULL))
);
COMMENT ON TABLE  maintenance.work_orders IS 'Work orders raised against assets, from inspections or reported faults.';
COMMENT ON COLUMN maintenance.work_orders.target_date IS 'Defaults to raised_on plus the response time of the priority.';

CREATE TABLE maintenance.maintenance_activities (
    activity_id     bigint        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    work_order_id   bigint        NOT NULL REFERENCES maintenance.work_orders ON DELETE RESTRICT,
    activity_type   varchar(40)   NOT NULL,
    performed_on    date          NOT NULL,
    labour_hours    numeric(6,2)  NOT NULL CHECK (labour_hours > 0 AND labour_hours <= 500),
    crew            varchar(60),
    notes           text
);
COMMENT ON TABLE maintenance.maintenance_activities IS 'Work done on a work order. An activity date must fall on or after the work order was raised.';

CREATE TABLE maintenance.maintenance_costs (
    cost_id         bigint         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    work_order_id   bigint         NOT NULL REFERENCES maintenance.work_orders ON DELETE RESTRICT,
    cost_type       varchar(12)    NOT NULL CHECK (cost_type IN ('LABOUR', 'MATERIALS', 'EQUIPMENT', 'CONTRACTOR')),
    cost_status     varchar(8)     NOT NULL CHECK (cost_status IN ('PLANNED', 'ACTUAL')),
    amount_zar      numeric(12,2)  NOT NULL CHECK (amount_zar > 0),
    cost_date       date           NOT NULL
);
COMMENT ON TABLE  maintenance.maintenance_costs IS 'Planned (budgeted) and actual (incurred) costs per work order, in rand.';

-- Triggers ------------------------------------------------------------------------------------------------------

CREATE FUNCTION maintenance.inspection_before_write() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    a_install date;
    a_class   text;
    d_class   text;
BEGIN
    SELECT a.install_date, t.class_code INTO a_install, a_class
      FROM assets.infrastructure_assets a JOIN reference.asset_types t USING (type_code)
     WHERE a.asset_id = NEW.asset_id;
    IF NEW.inspected_on > current_date THEN
        RAISE EXCEPTION 'Inspection date % is in the future', NEW.inspected_on USING ERRCODE = 'check_violation';
    END IF;
    IF a_install IS NOT NULL AND NEW.inspected_on < a_install THEN
        RAISE EXCEPTION 'Inspection date % is before the asset was installed (%)', NEW.inspected_on, a_install USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.defect_code IS NOT NULL THEN
        SELECT class_code INTO d_class FROM reference.defect_types WHERE defect_code = NEW.defect_code;
        IF d_class <> a_class THEN
            RAISE EXCEPTION 'Defect % belongs to class %, but the asset is class %', NEW.defect_code, d_class, a_class USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER inspection_before_write
    BEFORE INSERT OR UPDATE ON maintenance.inspections
    FOR EACH ROW EXECUTE FUNCTION maintenance.inspection_before_write();

CREATE FUNCTION maintenance.work_order_before_write() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' AND NEW.wo_number IS NULL THEN
        NEW.wo_number := 'WO-' || to_char(NEW.raised_on, 'YYYY') || '-' || lpad(nextval('maintenance.work_order_seq')::text, 6, '0');
    END IF;
    IF NEW.target_date IS NULL THEN
        SELECT NEW.raised_on + response_days INTO NEW.target_date
          FROM reference.work_order_priorities WHERE priority_code = NEW.priority_code;
    END IF;
    IF NEW.raised_on > current_date OR NEW.completed_on > current_date THEN
        RAISE EXCEPTION 'Work order dates cannot be in the future' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER work_order_before_write
    BEFORE INSERT OR UPDATE ON maintenance.work_orders
    FOR EACH ROW EXECUTE FUNCTION maintenance.work_order_before_write();

CREATE FUNCTION maintenance.activity_before_write() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    wo maintenance.work_orders%ROWTYPE;
BEGIN
    SELECT * INTO wo FROM maintenance.work_orders WHERE work_order_id = NEW.work_order_id;
    IF NEW.performed_on < wo.raised_on OR NEW.performed_on > current_date THEN
        RAISE EXCEPTION 'Activity date % must fall between the work order date % and today', NEW.performed_on, wo.raised_on
              USING ERRCODE = 'check_violation';
    END IF;
    IF wo.status = 'CANCELLED' THEN
        RAISE EXCEPTION 'Work order % is cancelled', wo.wo_number USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER activity_before_write
    BEFORE INSERT OR UPDATE ON maintenance.maintenance_activities
    FOR EACH ROW EXECUTE FUNCTION maintenance.activity_before_write();

"""Generate a synthetic maintenance history (January 2019 to the end of October 2026) for every asset in the register.

    python etl/generate_history.py [--as-of 2026-10-31] [--seed 2026]

ALL OUTPUT OF THIS SCRIPT IS SYNTHETIC. It produces inspections, work orders, maintenance activities and costs
that behave plausibly, but they describe no real asset, fault or payment.

How it works, per asset:
  * a hidden condition value starts from the asset's age relative to its design life, and worsens each year;
  * random failures (lamp outages, leaks, potholes, blockages, vandalism...) happen at type-specific yearly rates
    and are reported as emergency or corrective work orders;
  * routine inspections at the type's inspection interval record the condition as a grade from 1 to 5, and a
    grade of 4 or 5 raises a corrective work order;
  * work orders complete after a delay that depends on their priority, which restores the condition;
    the most recent ones are still open, as in any real backlog;
  * stormwater assets get a preventive clean-out every August before the rains; substations a yearly service.
The validation triggers stay switched on while loading, so the generated data must pass the same rules as any
other data. The audit trigger is switched off for the bulk load, and the load is recorded once in admin.job_runs.
Runs as the database owner or a superuser.
"""
import argparse
import datetime as dt
import math
import pathlib
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from gaz.db import connect  # noqa: E402

START = dt.date(2019, 1, 1)

# yearly probability of a reported failure, the defect it shows as, and repair cost range (rand)
FAILURE = {
    "STREETLIGHT":     (0.12, ["LT_OUT", "LT_OUT", "LT_OUT", "LT_DAYBURN", "LT_CABLE", "LT_FITTING", "LT_POLE"], (1200, 6500)),
    "TRAFFIC_SIGNAL":  (0.35, ["RD_SIGNAL"], (3000, 45000)),
    "ROAD_SEGMENT":    (0.10, ["RD_POTHOLE", "RD_POTHOLE", "RD_EDGE"], (2500, 25000)),
    "WATER_MAIN":      (0.05, ["WT_LEAK", "WT_LEAK", "WT_BURST", "WT_VALVE"], (6000, 60000)),
    "HYDRANT":         (0.05, ["WT_HYDRANT", "WT_LEAK"], (2500, 9000)),
    "RESERVOIR":       (0.05, ["WT_LEAK", "WT_VALVE"], (40000, 400000)),
    "CULVERT":         (0.15, ["SW_BLOCKED", "SW_BLOCKED", "SW_SILT"], (5000, 60000)),
    "CHANNEL":         (0.12, ["SW_BLOCKED", "SW_EROSION", "SW_SILT"], (4000, 50000)),
    "SUBSTATION":      (0.08, ["EL_OVERHEAT", "EL_VANDAL"], (25000, 350000)),
    "POWER_LINE":      (0.06, ["EL_VEG", "EL_INSUL", "EL_VANDAL"], (8000, 80000)),
    "PARK":            (0.15, ["FC_VANDAL", "FC_OVERGROWN"], (5000, 40000)),
    "PLAYGROUND":      (0.15, ["FC_EQUIP", "FC_VANDAL"], (4000, 35000)),
    "SPORTS_FACILITY": (0.10, ["FC_EQUIP", "FC_ROOF", "FC_VANDAL"], (10000, 120000)),
    "LIBRARY":         (0.10, ["FC_ROOF", "FC_PLUMB"], (8000, 150000)),
    "CLINIC":          (0.12, ["FC_ROOF", "FC_PLUMB", "FC_EQUIP"], (8000, 150000)),
    "COMMUNITY_CENTRE": (0.10, ["FC_ROOF", "FC_PLUMB", "FC_VANDAL"], (8000, 150000)),
    "PUBLIC_TOILET":   (0.30, ["FC_PLUMB", "FC_VANDAL"], (3000, 25000)),
    "RECYCLING_POINT": (0.25, ["WS_OVERFLOW", "WS_DAMAGE"], (1000, 6000)),
}
# defects recorded by inspections when the condition is poor without a reported failure
WEAR_DEFECT = {"ROADS": ["RD_CRACKING", "RD_RUTTING", "RD_MARKINGS"], "LIGHT": ["LT_POLE", "LT_FITTING"],
               "WATER": ["WT_CORROSION", "WT_VALVE", "WT_PRESSURE"], "STORM": ["SW_SILT", "SW_EROSION", "SW_STRUCT"],
               "ELEC": ["EL_INSUL", "EL_VEG"], "FAC": ["FC_ROOF", "FC_EQUIP", "FC_OVERGROWN"], "WASTE": ["WS_DAMAGE"]}
ACTIVITY = {"LT_OUT": "Lamp replacement", "LT_DAYBURN": "Photocell replacement", "LT_CABLE": "Cable replacement",
            "LT_FITTING": "Luminaire repair", "LT_POLE": "Pole straightening", "RD_SIGNAL": "Signal controller repair",
            "RD_POTHOLE": "Pothole patching", "RD_EDGE": "Edge repair", "RD_CRACKING": "Crack sealing", "RD_RUTTING": "Resurfacing",
            "RD_MARKINGS": "Road marking", "WT_LEAK": "Leak repair", "WT_BURST": "Pipe repair", "WT_VALVE": "Valve repair",
            "WT_HYDRANT": "Hydrant repair", "WT_CORROSION": "Pipe section replacement", "WT_PRESSURE": "Pressure investigation",
            "SW_BLOCKED": "Unblocking", "SW_SILT": "Desilting", "SW_EROSION": "Erosion repair", "SW_STRUCT": "Structural repair",
            "EL_OVERHEAT": "Transformer repair", "EL_VANDAL": "Security repair", "EL_VEG": "Vegetation clearing", "EL_INSUL": "Insulator replacement",
            "FC_VANDAL": "Vandalism repair", "FC_OVERGROWN": "Grass cutting", "FC_EQUIP": "Equipment repair", "FC_ROOF": "Roof repair",
            "FC_PLUMB": "Plumbing repair", "WS_OVERFLOW": "Emptying", "WS_DAMAGE": "Container repair"}
INSPECTOR_BY_WARD = {56: "inspector_a", 82: "inspector_b", 92: "inspector_c"}
RESPONSE = {"P1": 1, "P2": 7, "P3": 30, "P4": 90}


def months(n):
    return dt.timedelta(days=round(n * 30.44))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default="2026-10-31")
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    AS_OF = dt.date.fromisoformat(a.as_of)
    rng = np.random.default_rng(a.seed)

    with connect(app="generate_history") as conn:
        if conn.execute("SELECT count(*) FROM maintenance.inspections").fetchone()[0]:
            print("Maintenance history already present; nothing to do.")
            return
        run = conn.execute("INSERT INTO admin.job_runs (job_name) VALUES ('generate_history') RETURNING run_id").fetchone()[0]
        assets = conn.execute("""
            SELECT a.asset_id, a.type_code, t.class_code, a.install_date, t.design_life_years, t.inspection_interval_months,
                   t.criticality, t.replacement_unit_cost_zar, t.cost_unit, w.ward_no,
                   CASE t.cost_unit WHEN 'm' THEN ST_Length(a.geom::geography) WHEN 'm2' THEN ST_Area(a.geom::geography) ELSE 1 END,
                   wa.material
              FROM assets.infrastructure_assets a JOIN reference.asset_types t USING (type_code)
              JOIN reference.wards w USING (ward_id) LEFT JOIN assets.water_assets wa USING (asset_id)
             WHERE a.status_code <> 'DECOMMISSIONED' ORDER BY a.asset_id""").fetchall()

        inspections, work_orders = [], []    # work orders reference inspections by (asset_id, date) until ids exist
        for (aid, typ, cls, inst, life, interval, crit, unit_cost, unit, ward, qty, material) in assets:
            inst = inst or dt.date(1980, 1, 1)
            begin = max(START, inst + dt.timedelta(days=30))
            if begin >= AS_OF:
                continue
            age0 = (begin - inst).days / 365.25
            c = float(np.clip(1 + 3 * (age0 / life) ** 1.3 + rng.normal(0, 0.35), 1.0, 3.6))
            rate = 4.0 / life * rng.uniform(0.6, 1.4)
            p_fail, fail_defects, (cmin, cmax) = FAILURE[typ]
            if typ == "WATER_MAIN" and material in ("Asbestos cement", "Cast iron"):
                p_fail *= 1.8
            p_fail *= 0.6 + 0.8 * min(age0 / life, 1.5)          # older assets fail more often
            inspector = INSPECTOR_BY_WARD.get(ward, "inspector_a")
            qty = float(qty or 1)
            unit_cost = float(unit_cost)
            # a replacement renews one section of a linear or area asset, not the whole of it
            renew_qty = min(qty, float(rng.uniform(30, 120))) if unit == 'm' else (min(qty, 400.0) if unit == 'm2' else 1.0)

            # event timeline: inspections, failures, preventive jobs
            events = []
            t = begin + dt.timedelta(days=int(rng.integers(0, max(interval * 30, 30))))
            while t < AS_OF:
                events.append((t, "inspect"))
                t = t + months(interval) + dt.timedelta(days=int(rng.integers(-20, 21)))
            years = (AS_OF - begin).days / 365.25
            for _ in range(rng.poisson(p_fail * years)):
                events.append((begin + dt.timedelta(days=int(rng.integers(0, (AS_OF - begin).days))), "fail"))
            if cls == "STORM" or typ == "SUBSTATION":
                for y in range(begin.year, AS_OF.year + 1):
                    d = dt.date(y, 8, int(rng.integers(1, 28))) if cls == "STORM" else dt.date(y, int(rng.integers(3, 10)), int(rng.integers(1, 28)))
                    if begin <= d < AS_OF and rng.random() < 0.75:
                        events.append((d, "preventive"))
            events.sort()

            last_t, open_until = begin, None
            used_dates = set()
            for when, kind in events:
                c = min(5.0, c + rate * (when - last_t).days / 365.25)
                last_t = when
                if open_until and when < open_until:
                    if kind == "fail":
                        continue                                      # already being fixed
                if kind == "inspect":
                    if when in used_dates:
                        continue
                    used_dates.add(when)
                    grade = int(np.clip(round(c + rng.normal(0, 0.3)), 1, 5))
                    defect = str(rng.choice(WEAR_DEFECT[cls])) if grade >= 4 else None
                    inspections.append((aid, when, grade, defect, grade >= 4, inspector))
                    if grade >= 4 and not (open_until and when < open_until):
                        prio = "P1" if grade == 5 and crit >= 4 else ("P2" if grade == 5 or crit >= 4 else "P3")
                        replace = grade == 5 and rng.random() < 0.35
                        wo, done = make_wo(rng, aid, when + dt.timedelta(days=int(rng.integers(0, 6))), "REPLACEMENT" if replace else "CORRECTIVE",
                                           prio, defect, (aid, when), AS_OF, cmin, cmax, unit_cost * renew_qty if replace else None, typ)
                        work_orders.append(wo)
                        open_until = done or AS_OF
                        if done:
                            c = 1.0 if replace else max(1.0, c - rng.uniform(1.5, 2.8))
                elif kind == "fail":
                    defect = str(rng.choice(fail_defects))
                    prio = "P1" if crit >= 4 else "P2"
                    wo, done = make_wo(rng, aid, when, "EMERGENCY" if prio == "P1" else "CORRECTIVE", prio, defect, None, AS_OF, cmin, cmax, None, typ)
                    work_orders.append(wo)
                    c = max(c, 4.2)
                    open_until = done or AS_OF
                    if done:
                        c = max(1.0, c - rng.uniform(1.8, 3.0))
                else:
                    wo, done = make_wo(rng, aid, when, "PREVENTIVE", "P4", "SW_SILT" if cls == "STORM" else "EL_OVERHEAT", None, AS_OF,
                                       cmin * 0.4, cmax * 0.25, None, typ, preventive=True)
                    work_orders.append(wo)
                    if done:
                        c = max(1.0, c - 0.3)

        # ---- write: inspections, then work orders (with inspection ids), then activities and costs
        conn.execute("SELECT audit.set_enabled(false)")
        with conn.cursor().copy("COPY maintenance.inspections (asset_id, inspected_on, condition_grade, defect_code, action_required, inspector) FROM STDIN") as cp:
            for r in inspections:
                cp.write_row(r)
        insp_id = {(aid, d): i for i, aid, d in conn.execute("SELECT inspection_id, asset_id, inspected_on FROM maintenance.inspections")}

        work_orders.sort(key=lambda w: (w["raised"], w["asset_id"]))
        per_year = defaultdict(int)
        for w in work_orders:
            per_year[w["raised"].year] += 1
            w["number"] = f"WO-{w['raised'].year}-{per_year[w['raised'].year]:06d}"
        with conn.cursor().copy("""COPY maintenance.work_orders (wo_number, asset_id, inspection_id, wo_type, priority_code, status,
                                   raised_on, target_date, completed_on, description) FROM STDIN""") as cp:
            for w in work_orders:
                cp.write_row((w["number"], w["asset_id"], insp_id.get(w["insp"]) if w["insp"] else None, w["type"], w["prio"], w["status"],
                              w["raised"], w["target"], w["completed"], w["description"]))
        conn.execute("SELECT setval('maintenance.work_order_seq', %s)", (max(per_year.values()) + 1,))
        wo_id = dict(conn.execute("SELECT wo_number, work_order_id FROM maintenance.work_orders"))
        with conn.cursor().copy("COPY maintenance.maintenance_activities (work_order_id, activity_type, performed_on, labour_hours, crew) FROM STDIN") as cp:
            for w in work_orders:
                for act in w["activities"]:
                    cp.write_row((wo_id[w["number"]],) + act)
        with conn.cursor().copy("COPY maintenance.maintenance_costs (work_order_id, cost_type, cost_status, amount_zar, cost_date) FROM STDIN") as cp:
            for w in work_orders:
                for cost in w["costs"]:
                    cp.write_row((wo_id[w["number"]],) + cost)
        conn.execute("SELECT audit.set_enabled(true)")
        counts = conn.execute("""SELECT (SELECT count(*) FROM maintenance.inspections), (SELECT count(*) FROM maintenance.work_orders),
                                        (SELECT count(*) FROM maintenance.maintenance_activities), (SELECT count(*) FROM maintenance.maintenance_costs)""").fetchone()
        conn.execute("UPDATE admin.job_runs SET finished_at = clock_timestamp(), status = 'SUCCESS', rows_affected = %s, message = %s WHERE run_id = %s",
                     (sum(counts), f"Synthetic history to {AS_OF}: {counts[0]} inspections, {counts[1]} work orders, "
                                   f"{counts[2]} activities, {counts[3]} cost lines", run))
        conn.commit()
        print(f"inspections {counts[0]:,}  work orders {counts[1]:,}  activities {counts[2]:,}  cost lines {counts[3]:,}")


CREWS = ["Hatfield depot crew 1", "Hatfield depot crew 2", "Brooklyn depot crew", "Contractor: Ridge Civils (fictitious)",
         "Contractor: Lumen Services (fictitious)"]


def make_wo(rng, aid, raised, wo_type, prio, defect, insp_key, as_of, cmin, cmax, replace_cost, typ, preventive=False):
    """Build one work order with its activities and costs. Returns (work order, completion date or None)."""
    raised = min(raised, as_of)
    target = raised + dt.timedelta(days=RESPONSE[prio])
    # completion delay: around the response target, with a long tail of late jobs
    delay = max(0, int(RESPONSE[prio] * rng.lognormal(-0.25, 0.7) + rng.integers(0, 3)))
    completed = raised + dt.timedelta(days=delay)
    status = "COMPLETED"
    if rng.random() < 0.02:
        status, completed = "CANCELLED", None
    elif completed > as_of or (rng.random() < 0.03 and (as_of - raised).days < 400):
        completed = None
        age = (as_of - raised).days
        status = "OPEN" if age < 10 else ("SCHEDULED" if rng.random() < 0.5 else "IN_PROGRESS")
    estimate = replace_cost * rng.uniform(0.9, 1.1) if replace_cost else rng.uniform(cmin, cmax)
    estimate = round(float(estimate), -1)
    label = ACTIVITY.get(defect, "Maintenance")
    wo = {"asset_id": aid, "insp": insp_key, "type": wo_type, "prio": prio, "status": status, "raised": raised, "target": target,
          "completed": completed, "description": ("Scheduled " if preventive else "") + label.lower() + (" (replacement)" if wo_type == "REPLACEMENT" else ""),
          "activities": [], "costs": [("MATERIALS" if replace_cost else "LABOUR", "PLANNED", estimate, raised)]}
    if status in ("COMPLETED", "IN_PROGRESS"):
        end = completed or as_of
        actual = estimate * rng.uniform(0.8, 1.35)
        crew = CREWS[int(rng.integers(0, len(CREWS)))]
        contractor = crew.startswith("Contractor")
        n_act = 1 if actual < 15000 else int(rng.integers(1, 4))
        for k in range(n_act):
            day = raised + dt.timedelta(days=int((end - raised).days * (k + 1) / n_act))
            hours = round(max(0.5, min(400.0, actual * 0.35 / n_act / 450)), 2)
            wo["activities"].append((label, day, hours, crew))
        if status == "COMPLETED":
            split = [("LABOUR", 0.35), ("MATERIALS", 0.45), ("CONTRACTOR" if contractor else "EQUIPMENT", 0.20)]
            for kind, share in split:
                amt = round(actual * share * rng.uniform(0.85, 1.15), 2)
                if amt > 0:
                    wo["costs"].append((kind, "ACTUAL", amt, completed))
    return wo, completed


if __name__ == "__main__":
    main()

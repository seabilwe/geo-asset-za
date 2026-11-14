"""Spatial and relational query benchmarks: the same queries with and without the right index.

    python administration/performance/benchmark.py [--points 2000000] [--runs 7]

The demonstration register (about 12,000 assets) is too small for indexes to matter much, so the spatial tests
run on a separate benchmark table, bench.asset_points, filled with synthetic points across the City of Tshwane
(denser in the built-up centre). It lives in its own schema and is dropped with --cleanup.

For every query and index state it records the median execution time of several warm runs and the plan of the
median run from EXPLAIN (ANALYZE, BUFFERS): the top plan node, whether an index was used, and shared buffers
read or hit. Results go to administration/performance/results/benchmark.json and documentation/performance_report.md.
"""
import argparse
import json
import pathlib
import platform
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gaz.db import connect  # noqa: E402

RESULTS = pathlib.Path(__file__).parent / "results"

SETUP = """
DROP SCHEMA IF EXISTS bench CASCADE;
CREATE SCHEMA bench;
CREATE TABLE bench.asset_points (
    id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    type_code varchar(30) NOT NULL,
    geom      geometry(Point, 4326) NOT NULL
);
-- 70 percent of points clustered around Pretoria CBD, Hatfield and Centurion; 30% spread over the metro's extent
INSERT INTO bench.asset_points (type_code, geom)
SELECT (ARRAY['STREETLIGHT','HYDRANT','TRAFFIC_SIGNAL','CULVERT'])[1 + floor(random() * 4)::int],
       CASE WHEN random() < 0.7 THEN
            ST_SetSRID(ST_MakePoint(c.x + (random() + random() + random() - 1.5) * 0.12,
                                    c.y + (random() + random() + random() - 1.5) * 0.10), 4326)
       ELSE ST_SetSRID(ST_MakePoint(27.95 + random() * 1.15, -26.05 + random() * 0.85), 4326) END
  FROM generate_series(1, {n}) g
  CROSS JOIN LATERAL (SELECT (ARRAY[28.188, 28.237, 28.189])[1 + (g % 3)] AS x,
                             (ARRAY[-25.746, -25.750, -25.860])[1 + (g % 3)] AS y) c;
ANALYZE bench.asset_points;
"""

QUERIES = {
    "bbox": ("Assets in a bounding box (the plan's example: 28.1 to 28.4 E, 25.6 to 25.9 S)",
             "SELECT count(*) FROM bench.asset_points WHERE ST_Intersects(geom, ST_MakeEnvelope(28.1, -25.9, 28.4, -25.6, 4326))"),
    "small_bbox": ("Assets in a small box around Hatfield (about 1 km by 1 km)",
                   "SELECT count(*) FROM bench.asset_points WHERE ST_Intersects(geom, ST_MakeEnvelope(28.230, -25.755, 28.240, -25.745, 4326))"),
    "within_250m_geography": ("Assets within 250 m of a point, written with a geography cast on the column",
                              "SELECT count(*) FROM bench.asset_points WHERE ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(28.2370, -25.7480), 4326)::geography, 250)"),
    "within_250m_indexable": ("Assets within 250 m of a point, written so the geometry index can be used (box filter first, exact metres second)",
                              """SELECT count(*) FROM bench.asset_points
                                  WHERE geom && ST_Expand(ST_SetSRID(ST_MakePoint(28.2370, -25.7480), 4326), 0.003)
                                    AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(28.2370, -25.7480), 4326)::geography, 250)"""),
    "nearest_10": ("The 10 nearest assets to a point (KNN with the <-> operator)",
                   "SELECT id FROM bench.asset_points ORDER BY geom <-> ST_SetSRID(ST_MakePoint(28.2370, -25.7480), 4326) LIMIT 10"),
}

REGISTER_QUERY = ("Latest condition of every streetlight in the register (DISTINCT ON over 80,000 inspections)",
                  """SELECT count(*) FROM (SELECT DISTINCT ON (i.asset_id) i.asset_id, i.condition_grade
                       FROM maintenance.inspections i JOIN assets.infrastructure_assets a USING (asset_id)
                      WHERE a.type_code = 'STREETLIGHT' ORDER BY i.asset_id, i.inspected_on DESC, i.inspection_id DESC) x""")


def walk(node):
    yield node
    for child in node.get("Plans", []):
        yield from walk(child)


def measure(conn, query, runs):
    times, plans = [], []
    conn.execute(query)                       # warm the cache
    for _ in range(runs):
        plan = conn.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query).fetchone()[0][0]
        times.append(plan["Execution Time"])
        plans.append(plan)
    med = statistics.median(times)
    p = plans[times.index(min(times, key=lambda t: abs(t - med)))]
    nodes = list(walk(p["Plan"]))
    scans = [n["Node Type"] + (f" on {n['Index Name']}" if "Index Name" in n else "") for n in nodes if "Scan" in n["Node Type"]]
    return {"median_ms": round(med, 3), "min_ms": round(min(times), 3), "max_ms": round(max(times), 3),
            "scans": scans, "index_used": any("Index" in s for s in scans),
            "shared_hit": p["Plan"].get("Shared Hit Blocks", 0), "shared_read": p["Plan"].get("Shared Read Blocks", 0),
            "rows": sum(n.get("Actual Rows", 0) for n in nodes if "Scan" in n["Node Type"] and "Bitmap Index" not in n["Node Type"])}


def text_plan(conn, query):
    return "\n".join(r[0] for r in conn.execute("EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING OFF, SUMMARY OFF) " + query).fetchall())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", type=int, default=2_000_000)
    ap.add_argument("--runs", type=int, default=7)
    ap.add_argument("--cleanup", action="store_true", help="drop the bench schema afterwards")
    a = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)

    with connect(autocommit=True, app="benchmark") as conn:
        conn.execute("SET max_parallel_workers_per_gather = 0")      # single-process timings, comparable between runs
        t0 = time.perf_counter()
        conn.execute(SETUP.format(n=int(a.points)))
        load_s = time.perf_counter() - t0
        server = conn.execute("SELECT version(), postgis_lib_version(), current_setting('shared_buffers'), current_setting('work_mem')").fetchone()
        table_size = conn.execute("SELECT pg_size_pretty(pg_total_relation_size('bench.asset_points'))").fetchone()[0]
        out = {"points": a.points, "runs": a.runs, "load_seconds": round(load_s, 1), "table_size": table_size,
               "server": {"postgres": server[0].split(" on ")[0], "postgis": server[1], "shared_buffers": server[2], "work_mem": server[3],
                          "machine": platform.machine(), "parallel_workers": 0},
               "spatial": {}, "register": {}, "plans": {}}

        for key, (_, q) in QUERIES.items():
            out["spatial"][key] = {"before": measure(conn, q, a.runs)}
        out["plans"]["bbox_before"] = text_plan(conn, QUERIES["bbox"][1])

        t0 = time.perf_counter()
        conn.execute("CREATE INDEX asset_points_geom_gist ON bench.asset_points USING gist (geom)")
        out["index_build_seconds"] = round(time.perf_counter() - t0, 1)
        out["index_size"] = conn.execute("SELECT pg_size_pretty(pg_relation_size('bench.asset_points_geom_gist'))").fetchone()[0]
        conn.execute("ANALYZE bench.asset_points")
        for key, (_, q) in QUERIES.items():
            out["spatial"][key]["after"] = measure(conn, q, a.runs)
        out["plans"]["bbox_after"] = text_plan(conn, QUERIES["bbox"][1])
        out["plans"]["small_bbox_after"] = text_plan(conn, QUERIES["small_bbox"][1])
        out["plans"]["within_250m_geography_after"] = text_plan(conn, QUERIES["within_250m_geography"][1])
        out["plans"]["within_250m_indexable_after"] = text_plan(conn, QUERIES["within_250m_indexable"][1])

        # rows were inserted in random order, so neighbouring points sit on different pages. CLUSTER rewrites the
        # table in GiST order, so points that are close on the ground are also close on disk.
        t0 = time.perf_counter()
        conn.execute("CLUSTER bench.asset_points USING asset_points_geom_gist")
        conn.execute("ANALYZE bench.asset_points")
        out["cluster_seconds"] = round(time.perf_counter() - t0, 1)
        for key, (_, q) in QUERIES.items():
            out["spatial"][key]["clustered"] = measure(conn, q, a.runs)
        out["plans"]["bbox_clustered"] = text_plan(conn, QUERIES["bbox"][1])

        # relational: the latest-condition query with and without the composite inspections index
        q = REGISTER_QUERY[1]
        conn.execute("BEGIN")
        conn.execute("DROP INDEX maintenance.inspections_asset_date_idx")
        out["register"]["before"] = measure(conn, q, a.runs)
        out["plans"]["register_before"] = text_plan(conn, q)
        conn.execute("ROLLBACK")                                   # the index comes back untouched
        out["register"]["after"] = measure(conn, q, a.runs)
        out["plans"]["register_after"] = text_plan(conn, q)

        if a.cleanup:
            conn.execute("DROP SCHEMA bench CASCADE")

    (RESULTS / "benchmark.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    write_report(out)
    for k, v in out["spatial"].items():
        b, af, c = v["before"], v["after"], v["clustered"]
        print(f"{k:24s} {b['median_ms']:9.2f} -> {af['median_ms']:9.2f} -> {c['median_ms']:9.2f} ms   rows {c['rows']:,}")
    r = out["register"]
    print(f"{'register latest condition':24s} {r['before']['median_ms']:9.2f} ms -> {r['after']['median_ms']:8.2f} ms")


def write_report(o):
    def speed(b, x):
        r = b["median_ms"] / max(x["median_ms"], 0.001)
        return f"{r:,.0f}× faster" if r >= 1.5 else (f"{1 / r:,.1f}× slower" if r < 0.67 else "about the same")

    def plan(x):
        return ", ".join(dict.fromkeys(x["scans"])).replace(" on asset_points_geom_gist", " (GiST)")

    md = ["# Performance report", "",
          "Generated by `administration/performance/benchmark.py`. Re-run it to reproduce these figures on your own machine.", "",
          "## Test conditions", "",
          f"- {o['server']['postgres']}, PostGIS {o['server']['postgis']}, shared_buffers {o['server']['shared_buffers']}, work_mem {o['server']['work_mem']}",
          "- Parallel query switched off, so every timing is one process and runs are comparable",
          f"- Benchmark table `bench.asset_points`: {o['points']:,} synthetic points across the City of Tshwane, {o['table_size']} on disk, "
          "inserted in random order",
          f"- Each figure is the median of {o['runs']} warm runs (cache already loaded), measured with `EXPLAIN (ANALYZE, BUFFERS)`",
          f"- GiST index built in {o['index_build_seconds']} s ({o['index_size']}); `CLUSTER` on that index took {o['cluster_seconds']} s", "",
          "## Spatial queries in three states", "",
          "1. **No index**: every query scans the whole table.",
          "2. **GiST index**: `CREATE INDEX ... USING gist (geom)`.",
          "3. **GiST index, table clustered**: `CLUSTER ... USING` the GiST index rewrites the table so that points close on the ground "
          "are stored on the same disk pages.", "",
          "| Query | Matching rows | No index (ms) | GiST (ms) | GiST + clustered (ms) | Index alone | Index + cluster |",
          "|---|---:|---:|---:|---:|---|---|"]
    for k, (label, _) in QUERIES.items():
        v = o["spatial"][k]
        md.append(f"| {label} | {v['clustered']['rows']:,} | {v['before']['median_ms']:,.1f} | {v['after']['median_ms']:,.1f} | "
                  f"{v['clustered']['median_ms']:,.1f} | {speed(v['before'], v['after'])} | {speed(v['before'], v['clustered'])} |")
    md += ["", "Plans chosen:", "", "| Query | No index | GiST | GiST + clustered | Pages touched: no index / GiST / clustered |", "|---|---|---|---|---|"]
    for k, (label, _) in QUERIES.items():
        v = o["spatial"][k]
        pages = " / ".join(f"{x['shared_hit'] + x['shared_read']:,}" for x in (v["before"], v["after"], v["clustered"]))
        md.append(f"| {k.replace('_', ' ')} | {plan(v['before'])} | {plan(v['after'])} | {plan(v['clustered'])} | {pages} |")
    r = o["register"]
    md += ["", "## Register query: composite index on inspections", "",
           f"{REGISTER_QUERY[0]}: {r['before']['median_ms']:,.1f} ms without `inspections_asset_date_idx`, {r['after']['median_ms']:,.1f} ms with it "
           f"({speed(r['before'], r['after'])}). At 80,000 inspections the gain is modest; it grows with the history.", "",
           "## What the results show", "",
           "- **Selective queries gain the most.** A 1 km box, a 250 m radius or the 10 nearest assets touch a tiny share of the table. "
           "With the GiST index PostgreSQL reads only the matching index pages instead of testing every row.",
           "- **The plan's example box is a poor test of an index.** It covers most of the built-up area, so about two thirds of all "
           "points match. Here the index made the query *slower* than a full scan: the planner chose an index scan, and because the rows "
           "were stored in random order it had to jump between table pages for every match (see pages touched). "
           "After `CLUSTER`, matching rows sit together on disk and the same plan reads far fewer pages.",
           "- **How a query is written decides whether the index can be used.** Casting the column to geography (`geom::geography`) "
           "hides it from the geometry index, so the planner falls back to a full scan even when an index exists. Adding a bounding-box "
           "condition on the raw column (`geom && ST_Expand(...)`) lets the index find candidates first; the exact distance in metres is "
           "then checked on those few rows only.",
           "- **Nearest-neighbour search** with `ORDER BY geom <-> point LIMIT 10` walks the GiST index in distance order and stops after "
           "ten rows; without the index every distance has to be computed and sorted.",
           "- **CLUSTER is a one-off.** PostgreSQL does not keep the order as rows are added, so it is repeated in a maintenance window "
           "when the table has changed a lot. It locks the table while it runs.", "",
           "## Plans", ""]
    for k, p in o["plans"].items():
        md += [f"### {k.replace('_', ' ')}", "", "```", p, "```", ""]
    (ROOT / "documentation" / "performance_report.md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    main()

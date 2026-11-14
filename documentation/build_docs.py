"""Generate the entity relationship diagram and the data dictionary from the live database catalog.

    python documentation/build_docs.py

Writes documentation/erd.dot, erd.svg, erd.png and data_dictionary.md. Because both are read from the catalog
(table and column comments, constraints, foreign keys), they cannot drift from the schema. Needs Graphviz (dot).
"""
import html
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gaz.db import connect  # noqa: E402

OUT = ROOT / "documentation"
SCHEMAS = ["reference", "assets", "maintenance", "audit", "staging", "admin"]
ERD_SCHEMAS = ["reference", "assets", "maintenance", "staging", "audit"]
COLOURS = {"reference": "#E6DDC8", "assets": "#DCE3CF", "maintenance": "#F0DCC8", "staging": "#D9E4EA", "audit": "#E8E1EA", "admin": "#EEE"}
SKIP_ERD = {("staging", "validation_rules")}

COLS = """
SELECT n.nspname, c.relname, a.attnum, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
       pg_get_expr(d.adbin, d.adrelid), col_description(c.oid, a.attnum), a.attidentity
  FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
  LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
 WHERE n.nspname = ANY(%s) AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
 ORDER BY 1, 2, 3"""
TABLES = """
SELECT n.nspname, c.relname, obj_description(c.oid, 'pg_class'), c.reltuples::bigint, c.relrowsecurity
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = ANY(%s) AND c.relkind = 'r' ORDER BY 1, 2"""
CONS = """
SELECT n.nspname, c.relname, k.conname, k.contype, pg_get_constraintdef(k.oid),
       fn.nspname, fc.relname,
       (SELECT array_agg(a.attname ORDER BY x.i) FROM unnest(k.conkey) WITH ORDINALITY x(n, i)
          JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = x.n)
  FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
  LEFT JOIN pg_class fc ON fc.oid = k.confrelid LEFT JOIN pg_namespace fn ON fn.oid = fc.relnamespace
 WHERE n.nspname = ANY(%s) ORDER BY 1, 2, 4, 3"""
VIEWS = """
SELECT n.nspname, c.relname, CASE c.relkind WHEN 'm' THEN 'materialized view' ELSE 'view' END, obj_description(c.oid, 'pg_class')
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname IN ('operations', 'api', 'admin') AND c.relkind IN ('v', 'm') ORDER BY 1, 2"""
TRIGGERS = """
SELECT event_object_schema, event_object_table, trigger_name, string_agg(event_manipulation, ', ' ORDER BY event_manipulation), action_timing
  FROM information_schema.triggers WHERE event_object_schema = ANY(%s) GROUP BY 1, 2, 3, 5 ORDER BY 1, 2, 3"""


def short_type(t):
    return (t.replace("character varying", "varchar").replace("timestamp with time zone", "timestamptz")
             .replace("geometry(Geometry,4326)", "geometry(4326)").replace("geometry(MultiPolygon,4326)", "geometry(MultiPolygon)"))


def main():
    with connect(app="build_docs") as conn:
        cols = conn.execute(COLS, (SCHEMAS,)).fetchall()
        tables = conn.execute(TABLES, (SCHEMAS,)).fetchall()
        cons = conn.execute(CONS, (SCHEMAS,)).fetchall()
        views = conn.execute(VIEWS).fetchall()
        trigs = conn.execute(TRIGGERS, (SCHEMAS,)).fetchall()
        counts = {}
        for s, t, *_ in tables:
            counts[(s, t)] = conn.execute(f'SELECT count(*) FROM "{s}"."{t}"').fetchone()[0]

    pk, fk_cols, fks, checks, uniques = {}, {}, [], {}, {}
    for s, t, name, typ, defn, fs, ft, cols_ in cons:
        if typ == "p":
            pk[(s, t)] = set(cols_)
        elif typ == "f":
            fks.append((s, t, cols_, fs, ft))
            fk_cols.setdefault((s, t), set()).update(cols_)
        elif typ == "c":
            checks.setdefault((s, t), []).append((name, defn))
        elif typ == "u":
            uniques.setdefault((s, t), []).append((name, defn))

    by_table = {}
    for s, t, num, name, typ, nn, dflt, comment, ident in cols:
        by_table.setdefault((s, t), []).append((name, short_type(typ), nn, dflt, comment, ident))

    # ---- ERD (Graphviz) ------------------------------------------------------------------------------------
    lines = ['digraph erd {', '  graph [rankdir=LR, fontname="Helvetica", fontsize=11, nodesep=0.35, ranksep=1.1, pad=0.3, bgcolor="white"];',
             '  node [shape=plaintext, fontname="Helvetica", fontsize=9];', '  edge [color="#6B5B4B", arrowhead=crow, arrowtail=none, penwidth=0.9];']
    for s in ERD_SCHEMAS:
        lines.append(f'  subgraph cluster_{s} {{ label=<<b>{s}</b>>; fontsize=13; style="rounded"; color="#B9A383"; ')
        for (ts, t), cs in by_table.items():
            if ts != s or (s, t) in SKIP_ERD:
                continue
            rows = [f'<tr><td bgcolor="{COLOURS[s]}" colspan="2" align="left"><b>{t}</b></td></tr>']
            for name, typ, nn, dflt, comment, ident in cs:
                key = "PK " if name in pk.get((s, t), ()) else ("FK " if name in fk_cols.get((s, t), ()) else "")
                nm = f"<b>{html.escape(name)}</b>" if key == "PK " else html.escape(name)
                rows.append(f'<tr><td align="left" port="{name}">{key}{nm}</td><td align="left"><font color="#6B5B4B">{html.escape(typ)}</font></td></tr>')
            lines.append(f'    "{s}.{t}" [label=<<table border="0" cellborder="1" cellspacing="0" cellpadding="3">{"".join(rows)}</table>>];')
        lines.append("  }")
    for s, t, c, fs, ft in fks:
        if s in ERD_SCHEMAS and fs in ERD_SCHEMAS and (s, t) not in SKIP_ERD and (fs, ft) not in SKIP_ERD:
            lines.append(f'  "{fs}.{ft}" -> "{s}.{t}":"{c[0]}";')
    lines.append("}")
    (OUT / "erd.dot").write_text("\n".join(lines), encoding="utf-8")
    for fmt in ("svg", "png"):
        args = ["dot", f"-T{fmt}", str(OUT / "erd.dot"), "-o", str(OUT / f"erd.{fmt}")]
        if fmt == "png":
            args.insert(1, "-Gdpi=110")
        subprocess.run(args, check=True)

    # ---- Data dictionary ----------------------------------------------------------------------------------
    md = ["# Data dictionary", "",
          "Generated from the database catalog by `documentation/build_docs.py`. Row counts are from the demonstration build.", ""]
    for s in SCHEMAS:
        st = [(ts, t, desc, rls) for ts, t, desc, _, rls in tables if ts == s]
        if not st:
            continue
        md += [f"## Schema `{s}`", ""]
        for _, t, desc, rls in st:
            md += [f"### `{s}.{t}`", "", (desc or "").strip(), "",
                   f"Rows: {counts[(s, t)]:,}" + ("  ·  Row-level security: on" if rls else ""), "",
                   "| Column | Type | Null | Default | Description |", "|---|---|---|---|---|"]
            for name, typ, nn, dflt, comment, ident in by_table[(s, t)]:
                key = " (PK)" if name in pk.get((s, t), ()) else (" (FK)" if name in fk_cols.get((s, t), ()) else "")
                d = "identity" if ident else (dflt or "")
                md.append(f"| `{name}`{key} | {typ} | {'no' if nn else 'yes'} | {d.replace('|', '/')} | {(comment or '').replace('|', '/')} |")
            fk_lines = [f"`{', '.join(c)}` → `{fs}.{ft}`" for ss, tt, c, fs, ft in fks if (ss, tt) == (s, t)]
            ck = checks.get((s, t), []) + uniques.get((s, t), [])
            tr = [f"`{n}` ({timing.lower()} {ev.lower()})" for ss, tt, n, ev, timing in trigs if (ss, tt) == (s, t)]
            if fk_lines:
                md += ["", "Foreign keys: " + "; ".join(fk_lines)]
            if ck:
                md += ["", "Constraints:", ""] + [f"- `{n}`: `{d}`" for n, d in ck]
            if tr:
                md += ["", "Triggers: " + "; ".join(tr)]
            md.append("")
    md += ["## Views", "", "| View | Kind | Description |", "|---|---|---|"]
    md += [f"| `{s}.{v}` | {k} | {(d or '').replace('|', '/')} |" for s, v, k, d in views]
    (OUT / "data_dictionary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("wrote erd.svg, erd.png, data_dictionary.md")


if __name__ == "__main__":
    main()

"""Generate the entity relationship diagram and the data dictionary from the live database catalog.

    python documentation/build_docs.py

Writes documentation/erd.dot, erd.svg, erd.png and data_dictionary.md. Because both are read from the catalog
(table and column comments, constraints, foreign keys), they cannot drift from the schema. Needs Graphviz (dot).
"""
import html
import re
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

    # ---- ERD (Graphviz), crow's foot notation ---------------------------------------------------------------
    # Each column row is one table cell carrying a port, so relationship lines start and end exactly on the
    # table edge at the column they join (shape=plain has no margin, so there is no gap).
    # Parent end:  || exactly one (NOT NULL foreign key)   |o zero or one (nullable foreign key)
    # Child end:   o< zero or many                          o| zero or one (1:1 detail table, foreign key is the primary key)
    nullable = {(s, t, name): not nn for (s, t), cs in by_table.items() for name, typ, nn, *_ in cs}
    lines = ['digraph erd {',
             '  graph [rankdir=LR, fontname="Helvetica", fontsize=11, nodesep=0.4, ranksep=1.2, pad=0.3, bgcolor="white", splines=true, newrank=true];',
             '  node [shape=plain, fontname="Helvetica", fontsize=9];',
             '  edge [color="#5A4A3C", penwidth=1.0, dir=both, arrowsize=0.9];']

    def row(port, name, typ, key):
        nm = f"<b>{html.escape(name)}</b>" if key == "PK" else html.escape(name)
        return (f'<tr><td port="{port}" align="left" balign="left" bgcolor="white"><table border="0" cellspacing="0" cellpadding="0"><tr>'
                f'<td align="left" width="34">{f'<font color="#7A4B26">{key}</font>' if key else ' '}</td><td align="left" width="128">{nm}</td>'
                f'<td align="left" width="96"><font color="#6B5B4B">{html.escape(typ)}</font></td></tr></table></td></tr>')

    for s in ERD_SCHEMAS:
        lines.append(f'  subgraph cluster_{s} {{ label=<<b>{s}</b>>; fontsize=13; style="rounded"; color="#B9A383"; margin=14;')
        for (ts, t), cs in by_table.items():
            if ts != s or (s, t) in SKIP_ERD:
                continue
            rows = [f'<tr><td bgcolor="{COLOURS[s]}" align="left"><b>{t}</b></td></tr>']
            for name, typ, nn, dflt, comment, ident in cs:
                key = "PK" if name in pk.get((s, t), ()) else ("FK" if name in fk_cols.get((s, t), ()) else "")
                rows.append(row(name, name, typ, key))
            lines.append(f'    "{s}.{t}" [label=<<table border="1" cellborder="1" cellspacing="0" cellpadding="3" color="#5A4A3C">{"".join(rows)}</table>>];')
        lines.append("  }")
    for s, t, c, fs, ft in fks:
        if s in ERD_SCHEMAS and fs in ERD_SCHEMAS and (s, t) not in SKIP_ERD and (fs, ft) not in SKIP_ERD:
            parent_col = sorted(pk[(fs, ft)])[0]
            one_to_one = set(c) == pk.get((s, t), set())
            tail = "teeodot" if nullable[(s, t, c[0])] else "teetee"
            head = "teeodot" if one_to_one else "crowodot"
            lines.append(f'  "{fs}.{ft}":"{parent_col}" -> "{s}.{t}":"{c[0]}" [arrowtail={tail}, arrowhead={head}];')
    # notation key
    lines += ['  subgraph cluster_key { label=<<b>Notation</b>>; fontsize=12; style="rounded"; color="#B9A383"; margin=10;',
              '    k1a [label="", shape=point, width=0.01]; k1b [label=<one parent, zero or many children>, shape=plaintext, fontsize=10];',
              '    k2a [label="", shape=point, width=0.01]; k2b [label=<one parent, zero or one child (detail table)>, shape=plaintext, fontsize=10];',
              '    k3a [label="", shape=point, width=0.01]; k3b [label=<optional parent (nullable foreign key)>, shape=plaintext, fontsize=10];',
              '    k1a -> k1b [arrowtail=teetee, arrowhead=crowodot, minlen=1]; k2a -> k2b [arrowtail=teetee, arrowhead=teeodot, minlen=1];',
              '    k3a -> k3b [arrowtail=teeodot, arrowhead=crowodot, minlen=1];', '  }']
    lines.append("}")
    (OUT / "erd.dot").write_text("\n".join(lines), encoding="utf-8")
    for fmt in ("svg", "png"):
        args = ["dot", f"-T{fmt}", str(OUT / "erd.dot"), "-o", str(OUT / f"erd.{fmt}")]
        if fmt == "png":
            args.insert(1, "-Gdpi=110")
        subprocess.run(args, check=True)
    svg = (OUT / "erd.svg").read_text(encoding="utf-8")
    svg = re.sub(r'<svg width="[\d.]+pt" height="[\d.]+pt"', '<svg width="100%" style="max-width:2200px;height:auto"', svg, count=1)
    (OUT / "erd.svg").write_text(svg, encoding="utf-8")

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
    privilege_matrix()
    print("wrote erd.svg, erd.png, data_dictionary.md, privilege_matrix.md")


ROLES = ["gaz_admin", "gaz_manager", "gaz_inspector", "gaz_analyst", "gaz_etl", "gaz_web", "gaz_monitor"]
SCHEMA_ORDER = ["reference", "assets", "maintenance", "operations", "audit", "staging", "api", "admin"]


def privilege_matrix():
    """Effective privileges of each group role on every table and view, read from the catalog with has_table_privilege."""
    with connect(app="build_docs") as conn:
        objs = conn.execute("""SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                                WHERE n.nspname = ANY(%s) AND c.relkind IN ('r','v','m') ORDER BY array_position(%s, n.nspname::text), c.relname""",
                            (SCHEMA_ORDER, SCHEMA_ORDER)).fetchall()
        md = ["# Privilege matrix", "",
              "Generated from the catalog by `documentation/build_docs.py` with `has_table_privilege`, so it shows what each group role "
              "can actually do, including privileges inherited through membership. S = select, I = insert, U = update "
              "(u = some columns only), D = delete. Row-level security further limits `gaz_inspector` on `maintenance.inspections`.", "",
              "| Object | " + " | ".join(r.replace("gaz_", "") for r in ROLES) + " |", "|---" * (len(ROLES) + 1) + "|"]
        for s, t in objs:
            cells = []
            for r in ROLES:
                q = f"{s}.{t}"
                p = "".join(code for code, priv in (("S", "SELECT"), ("I", "INSERT"), ("U", "UPDATE"), ("D", "DELETE"))
                            if conn.execute("SELECT has_table_privilege(%s, %s, %s)", (r, q, priv)).fetchone()[0])
                if "U" not in p and conn.execute("SELECT has_any_column_privilege(%s, %s, 'UPDATE')", (r, q)).fetchone()[0]:
                    p += "u"
                cells.append(p or "·")
            md.append(f"| `{s}.{t}` | " + " | ".join(cells) + " |")
        funcs = conn.execute("""SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                                 WHERE n.nspname = ANY(%s) AND p.prorettype <> 'trigger'::regtype ORDER BY 1""", (SCHEMA_ORDER,)).fetchall()
        md += ["", "## Functions (EXECUTE)", "", "| Function | " + " | ".join(r.replace("gaz_", "") for r in ROLES) + " |", "|---" * (len(ROLES) + 1) + "|"]
        for (f,) in funcs:
            md.append(f"| `{f}` | " + " | ".join("X" if conn.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE')", (r, f)).fetchone()[0] else "·"
                                                  for r in ROLES) + " |")
    (OUT / "privilege_matrix.md").write_text("\n".join(md) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

"""
Generates OMOPCDM_duckdb_5.4_local.sql: a DuckDB-compatible DDL with all
constraints inline. Strategy:
  - PKs inline on every table
  - FK constraints inline ONLY for non-circular, non-concept references
    (concept/vocabulary/domain/concept_class/relationship have circular FKs
    and concept is unpopulated in demo; these are excluded)
  - Tables ordered so referenced tables are defined before referencing tables
"""
import re
from pathlib import Path
from collections import defaultdict, deque

DDL_DIR = Path('/Users/croeder/git/matchbox_scripts/ddl')

def strip_schema(s):
    return s.replace('@cdmDatabaseSchema.', '').strip()

# ── 1. Parse PKs ─────────────────────────────────────────────────────────
pk_map = {}  # table → pk_col
for line in (DDL_DIR / 'OMOPCDM_duckdb_5.4_primary_keys.sql').read_text().splitlines():
    m = re.match(r'ALTER TABLE @cdmDatabaseSchema\.(\w+)\s+ADD CONSTRAINT \w+\s+PRIMARY KEY\s*\((\w+)\)',
                 line.strip(), re.IGNORECASE)
    if m:
        pk_map[m.group(1).lower()] = m.group(2).lower()

# ── 2. Parse FKs ──────────────────────────────────────────────────────────
fk_map = defaultdict(list)  # table → [(cname, col, ref_table, ref_col)]
for line in (DDL_DIR / 'OMOPCDM_duckdb_5.4_constraints.sql').read_text().splitlines():
    m = re.match(r'ALTER TABLE @cdmDatabaseSchema\.(\w+)\s+ADD CONSTRAINT (\w+)\s+'
                 r'FOREIGN KEY\s*\((\w+)\)\s+REFERENCES @cdmDatabaseSchema\.(\w+)\s*\((\w+)\)',
                 line.strip(), re.IGNORECASE)
    if m:
        fk_map[m.group(1).lower()].append(
            (m.group(2), m.group(3), m.group(4).lower(), m.group(5)))

# ── 3. Parse CREATE TABLE bodies ──────────────────────────────────────────
raw = strip_schema((DDL_DIR / 'OMOPCDM_duckdb_5.4_ddl.sql').read_text())
tables = {}   # table_name → list of column definition strings
for m in re.finditer(r'CREATE\s+TABLE\s+(\w+)\s*\((.*?)\)\s*;', raw, re.IGNORECASE|re.DOTALL):
    tbl = m.group(1).lower()
    col_lines = [l.strip().rstrip(',') for l in m.group(2).splitlines()
                 if l.strip() and not l.strip().startswith('--')]
    tables[tbl] = col_lines

# ── 4. Determine which FKs to include ────────────────────────────────────
# Vocabulary tables have circular FKs and concept is unpopulated in demo.
# Exclude all FKs that reference these tables.
CIRCULAR_VOCAB = {'concept', 'vocabulary', 'domain', 'concept_class', 'relationship'}

safe_fks = {}  # table → [(cname, col, ref_table, ref_col)] — only includeable FKs
for tbl, fks in fk_map.items():
    kept = [(c, col, rt, rc) for c, col, rt, rc in fks if rt.lower() not in CIRCULAR_VOCAB]
    if kept:
        safe_fks[tbl] = kept

# ── 5. Topological sort by FK dependency ─────────────────────────────────
deps = defaultdict(set)  # table → set of tables that must precede it
for tbl, fks in safe_fks.items():
    for _, _, ref_table, _ in fks:
        if ref_table.lower() != tbl:
            deps[tbl].add(ref_table.lower())

all_tables = list(tables.keys())
in_degree = {t: 0 for t in all_tables}
adj = defaultdict(set)
for tbl, prerequisites in deps.items():
    for pre in prerequisites:
        if pre in tables:
            adj[pre].add(tbl)
            in_degree[tbl] += 1

queue = deque(t for t in all_tables if in_degree[t] == 0)
order = []
while queue:
    node = queue.popleft()
    order.append(node)
    for neighbor in adj[node]:
        in_degree[neighbor] -= 1
        if in_degree[neighbor] == 0:
            queue.append(neighbor)
# Any tables not reached (cycles) go at the end
remaining = [t for t in all_tables if t not in order]
order += remaining

# ── 6. Generate output ────────────────────────────────────────────────────
out = [
    '-- DuckDB-local OMOP CDM 5.4 DDL with inline PK and FK constraints.',
    '-- Generated from _ddl.sql + _primary_keys.sql + _constraints.sql.',
    '-- FK constraints to concept/vocabulary/domain/concept_class/relationship',
    '-- are excluded: those tables have circular FKs and concept is unpopulated',
    '-- in demo deployments. Regenerate with generate_local_ddl.py.',
    '',
]
for tbl in order:
    if tbl not in tables:
        continue
    pk_col = pk_map.get(tbl)
    col_defs = []
    for cl in tables[tbl]:
        col_name = cl.split()[0].lower()
        if pk_col and col_name == pk_col:
            cl = cl + ' PRIMARY KEY'
        col_defs.append(cl)
    fk_defs = [
        f'CONSTRAINT {c} FOREIGN KEY ({col}) REFERENCES {rt}({rc})'
        for c, col, rt, rc in safe_fks.get(tbl, [])
    ]
    all_defs = col_defs + fk_defs
    body = ',\n'.join(f'    {d}' for d in all_defs)
    out.append(f'CREATE TABLE {tbl} (')
    out.append(body)
    out.append(');')
    out.append('')

out_path = DDL_DIR / 'OMOPCDM_duckdb_5.4_local.sql'
out_path.write_text('\n'.join(out))
print(f'Tables: {len(order)}, Safe FKs on {len(safe_fks)} tables')
print(f'Excluded vocab-circular FKs targeting: {CIRCULAR_VOCAB}')
print(f'Written: {out_path}')

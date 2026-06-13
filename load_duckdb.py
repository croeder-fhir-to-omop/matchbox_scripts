"""
Load all FHIR fixture JSON files through matchbox transforms and insert into
an OMOP CDM 5.4 DuckDB database.
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from omop_to_csv import COLUMNS as OMOP_COLUMNS
from transforms import (
    transform_allergy,
    transform_allergy_server,
    transform_bp_diastolic,
    transform_bp_panel,
    transform_bp_systolic,
    transform_condition,
    transform_encounter,
    transform_encounter_server,
    transform_immunization,
    transform_measurement,
    transform_medication,
    transform_medication_server,
    transform_observation,
    transform_patient,
    transform_procedure,
    transform_vital_signs,
)

SCRIPTS_DIR = Path(__file__).parent
DDL_DIR = SCRIPTS_DIR / 'ddl'
DB_PATH = os.environ.get('OMOP_DB_PATH', '/omop/omop.ddb')
CSV_DIR = Path(os.environ.get('OMOP_CSV_DIR', str(Path(DB_PATH).parent / 'csv')))
REPORT_PATH = os.path.join(os.path.dirname(DB_PATH), 'etl_report.html')
IG_VERSION = os.environ.get('OMOP_IG_VERSION', '1.0.1')
DEFAULT_FIXTURES_DIR = SCRIPTS_DIR / os.environ.get('FIXTURES_DIR', 'test_files')

# ORDER IS SIGNIFICANT: the local DDL enforces FK constraints, so referenced tables
# must be populated before the tables that reference them. person must be inserted
# before any clinical table (all carry person_id FK); visit_occurrence before any
# table that carries a visit_occurrence_id FK.
FIXTURE_TRANSFORMS = [
    # Insert order matters: person must precede all clinical tables (FK person_id);
    # visit_occurrence must precede clinical tables that carry encounter references.

    # 1. Persons
    ('patient*.json',         transform_patient,          'person',               'PersonMap'),
    ('Patient-Pat-*.json',    transform_patient,          'person',               'PersonMap'),

    # 2. Visits (must exist before condition, procedure, observation, drug, measurement)
    ('encounter_*.json',      transform_encounter,        'visit_occurrence',     'EncounterVisitMap'),
    ('encounter_*.json',      transform_encounter_server, 'visit_occurrence',     'EncounterVisitMapServer'),

    # 3. Clinical records
    ('condition_*.json',      transform_condition,        'condition_occurrence', 'ConditionMap'),
    ('procedure_*.json',      transform_procedure,        'procedure_occurrence', 'ProcedureMap'),
    ('immunization_*.json',   transform_immunization,     'drug_exposure',        'ImmunizationMap'),
    ('observation_*weight*.json',           transform_measurement, 'measurement',  'MeasurementMap'),
    ('observation_*creatinine*.json',       transform_measurement, 'measurement',  'MeasurementMap'),
    ('observation_*sodium*.json',           transform_measurement, 'measurement',  'MeasurementMap'),
    ('observation_*NEG*.json',              transform_measurement, 'measurement',  'MeasurementMap'),
    ('observation_*temp*.json',             transform_vital_signs, 'measurement',  'SimpleVitalSignsMap'),
    ('observation_*heartrate*.json',        transform_vital_signs, 'measurement',  'SimpleVitalSignsMap'),
    ('observation_bp*.json',                transform_bp_panel,    'measurement',  'BloodPressureVitalSignsMap'),
    ('observation_bp*.json',                transform_bp_systolic, 'measurement',  'BloodPressureSystolicMap'),
    ('observation_bp*.json',                transform_bp_diastolic,'measurement',  'BloodPressureDiastolicMap'),
    ('observation_*blood*.json',            transform_bp_panel,    'measurement',  'BloodPressureVitalSignsMap'),
    ('observation_*blood*.json',            transform_bp_systolic, 'measurement',  'BloodPressureSystolicMap'),
    ('observation_*blood*.json',            transform_bp_diastolic,'measurement',  'BloodPressureDiastolicMap'),
    ('observation_smoking*.json',           transform_observation, 'observation',  'ObservationMap'),
    ('allergy_*.json',        transform_allergy,          'observation',          'AllergyMap'),
    ('allergy_*.json',        transform_allergy_server,   'observation',          'AllergyMapServer'),
    ('medication*.json',      transform_medication,       'drug_exposure',        'MedicationMap'),
    ('medication*.json',      transform_medication_server,'drug_exposure',        'MedicationMapServer'),
]

STATUS_COLOR = {
    'OK':         '#2d8a4e',
    'SUPPRESSED': '#888',
    'WARN':       '#c07a00',
    'SKIP':       '#c0392b',
}


def load_ddl(con):
    # Use the local DDL file which has PKs and non-circular FKs inline —
    # required because DuckDB does not support ALTER TABLE ADD CONSTRAINT FOREIGN KEY.
    # Regenerate from source files with ddl/generate_local_ddl.py when the schema changes.
    sql = (DDL_DIR / 'OMOPCDM_duckdb_5.4_local.sql').read_text()
    for statement in sql.split('\n\n'):
        statement = statement.strip()
        if not statement or statement.startswith('--'):
            continue
        try:
            con.execute(statement)
        except duckdb.CatalogException:
            # Table already exists from a prior load — expected on re-run.
            pass


def insert(con, table, row):
    if not row:
        return False, None
    cols = [k for k, v in row.items() if v != '' and v is not None]
    vals = [row[c] for c in cols]
    placeholders = ', '.join(['?'] * len(cols))
    col_list = ', '.join(cols)
    try:
        con.execute(
            f'INSERT INTO {table} ({col_list}) VALUES ({placeholders})',
            vals,
        )
        return True, None
    except (duckdb.ConstraintException, duckdb.ConversionException) as e:
        msg = str(e).split('\n')[0]
        print(f'  WARN insert into {table}: {msg}', file=sys.stderr)
        return False, msg


def _root_cause(detail):
    if not detail:
        return ''
    if 'NOT NULL constraint' in detail:
        field = detail.split('.')[-1] if '.' in detail else detail
        interpretation = (f'<code>{field}</code> is NOT NULL but was not populated — '
                          f'StructureMap (OMOP IG v{IG_VERSION}) may not call translate() for this field, '
                          f'or translate() returned null (code not found on terminology server).')
    elif 'Could not convert string' in detail:
        import re
        m = re.search(r"string '([^']+)'", detail)
        val = m.group(1) if m else '?'
        interpretation = (f'StructureMap placed source code/label <code>{val}</code> '
                          f'directly into an integer concept_id field instead of translating it.')
    elif 'violates primary key constraint' in detail:
        interpretation = ('Two source FHIR resources produced the same OMOP primary key — '
                          'they share the same FHIR resource <code>id</code> field, '
                          'or the same source fixture is processed by multiple maps.')
    elif 'unknown resourceType' in detail:
        interpretation = 'matchbox returned an unrecognised resourceType — StructureMap may have failed silently.'
    elif 'Exception executing transform' in detail or 'HAPI' in detail:
        interpretation = 'matchbox transform error (see detail below).'
    else:
        interpretation = ''
    raw = f'<br><span style="font-size:0.8em;color:#888;font-family:monospace">{detail}</span>'
    return interpretation + raw


def write_report(results, csv_rows=None):
    counts = {s: sum(1 for r in results if r['status'] == s) for s in STATUS_COLOR}
    csv_map = csv_rows or {}
    rows_html = ''
    for r in results:
        color = STATUS_COLOR.get(r['status'], '#000')
        detail = r.get('detail', '') or ''
        root = _root_cause(detail)
        table = r.get('table', '')
        table_csv = csv_map.get(table)
        if table_csv:
            n = len(table_csv)
            csv_cell = (
                f'<a href="csv/{table}.html" target="_blank">{table}.csv&nbsp;({n})</a>'
                f'&nbsp;<a href="csv/{table}.csv" download>&#8595;dl</a>'
            )
        else:
            csv_cell = ''
        rows_html += (
            f'<tr>'
            f'<td><a href="fixtures/{r["file"]}">{r["file"]}</a></td>'
            f'<td>{f"""<a href="https://hl7.org/fhir/uv/omop/StructureMap-{r["map"]}.html" target="_blank"><code>{r["map"]}</code></a>""" if r.get("map") else ""}</td>'
            f'<td>{table}</td>'
            f'<td style="color:{color};font-weight:bold">{r["status"]}</td>'
            f'<td>{csv_cell}</td>'
            f'<td style="font-size:0.85em;color:#555">{root}</td>'
            f'</tr>\n'
        )
    summary = ' &nbsp;|&nbsp; '.join(
        f'<span style="color:{STATUS_COLOR[s]}">{s}: {counts[s]}</span>'
        for s in STATUS_COLOR
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>ETL Report</title>
<style>
  body {{ font-family: sans-serif; margin: 2em; background: #f9f9f9; }}
  h1 {{ color: #333; }}
  .note {{ background:#fff8e1; border-left:4px solid #c07a00; padding:0.75em 1em; margin:1em 0; font-size:0.95em; }}
  .summary {{ margin: 1em 0; font-size: 1.1em; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff; }}
  th {{ background: #333; color: #fff; padding: 8px 12px; text-align: left; }}
  td {{ padding: 6px 12px; border-bottom: 1px solid #ddd; vertical-align:top; }}
  tr:hover {{ background: #f0f0f0; }}
  code {{ background:#eee; padding:1px 4px; border-radius:3px; font-size:0.9em; }}
</style>
</head><body>
<h1>FHIR &rarr; OMOP ETL Report</h1>
<p>Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
<div class="note">
  <strong>Known limitation — OMOP IG StructureMaps v{IG_VERSION}:</strong>
  The StructureMaps translate FHIR field <em>structure</em> to OMOP field names
  but do not implement concept_id translation. FHIR gender, LOINC, SNOMED, and
  RxNorm codes are not resolved to OMOP integer concept_ids by the maps.
  Echidna (<code>txServer</code>) is configured in matchbox but the maps do not
  call <code>translate()</code> for concept lookup. Full concept mapping requires
  either updated StructureMaps or a post-transform vocabulary lookup step.
</div>
<div class="summary">{summary}</div>
<table>
<tr><th>File</th><th>StructureMap</th><th>Table</th><th>Status</th><th>CSV</th><th>Root Cause</th></tr>
{rows_html}
</table>
</body></html>"""
    Path(REPORT_PATH).write_text(html)
    print(f'ETL report written to {REPORT_PATH}')
    return html


def _csv_viewer_html(table, rows):
    cols = list(rows[0].keys())
    headers = ''.join(f'<th>{c}</th>' for c in cols)
    body = ''
    for row in rows:
        cells = ''.join(f'<td>{row.get(c, "")}</td>' for c in cols)
        body += f'<tr>{cells}</tr>\n'
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>{table}</title>
<style>
  body {{ font-family: monospace; margin: 1em; background: #f9f9f9; }}
  h1 {{ font-size: 1.1em; color: #333; }}
  table {{ border-collapse: collapse; background: #fff; }}
  th {{ background: #333; color: #fff; padding: 4px 10px; text-align: left; }}
  td {{ padding: 3px 10px; border-bottom: 1px solid #ddd; white-space: nowrap; }}
  tr:hover {{ background: #f0f0f0; }}
  .dl {{ float: right; font-size: 0.9em; }}
</style>
</head><body>
<h1>{table} <span class="dl"><a href="{table}.csv" download>&#8595; download CSV</a></span></h1>
<p>{len(rows)} rows</p>
<table><tr>{headers}</tr>
{body}</table>
</body></html>"""


def write_csvs(csv_rows):
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    for table, rows in csv_rows.items():
        if not rows:
            continue
        out = CSV_DIR / f'{table}.csv'
        with out.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        (CSV_DIR / f'{table}.html').write_text(_csv_viewer_html(table, rows))
        print(f'  CSV {out} ({len(rows)} rows)')
    print(f'CSV files written to {CSV_DIR}')


def run(fixture_dirs=None):
    if fixture_dirs is None:
        fixture_dirs = [DEFAULT_FIXTURES_DIR]
    elif isinstance(fixture_dirs, Path):
        fixture_dirs = [fixture_dirs]

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    con = duckdb.connect(DB_PATH)
    results = []
    csv_rows: dict[str, list] = {}

    print('Loading OMOP CDM 5.4 schema...')
    load_ddl(con)

    con.execute("""
        INSERT INTO cdm_source (
            cdm_source_name, cdm_source_abbreviation, cdm_holder,
            source_release_date, cdm_release_date,
            cdm_version, cdm_version_concept_id, vocabulary_version
        ) VALUES (
            'FHIR-OMOP Demo', 'FHIR-OMOP', 'Demo',
            '2024-01-01', '2024-01-01',
            'v5.4', 0, 'n/a'
        )
    """)

    for fixture_dir in fixture_dirs:
        print(f'Fixtures dir: {fixture_dir}')
        _load_fixture_dir(con, fixture_dir, results, csv_rows)

    con.close()
    print(f'Done. Database written to {DB_PATH}')
    write_csvs(csv_rows)
    write_report(results, csv_rows)


def _load_fixture_dir(con, fixture_dir, results, csv_rows):
    processed = set()
    for pattern, transform_fn, table, map_name in FIXTURE_TRANSFORMS:
        paths = sorted(fixture_dir.glob(pattern))
        for path in paths:
            processed.add(path.name)
            resource = json.loads(path.read_text())
            try:
                result = transform_fn(resource)
            except Exception as e:
                msg = str(e).split('\n')[0]
                print(f'  SKIP {path.name}: {msg}', file=sys.stderr)
                results.append({'file': path.name, 'map': map_name, 'table': table, 'status': 'SKIP', 'detail': msg})
                continue
            if result is None:
                print(f'  SUPPRESSED {path.name}')
                results.append({'file': path.name, 'map': map_name, 'table': table, 'status': 'SUPPRESSED'})
                continue
            resource_type = result.get('resourceType')
            cols = OMOP_COLUMNS.get(resource_type)
            if cols is None:
                msg = f'unknown resourceType {resource_type!r}'
                print(f'  SKIP {path.name}: {msg}', file=sys.stderr)
                results.append({'file': path.name, 'map': map_name, 'table': table, 'status': 'SKIP', 'detail': msg})
                continue
            row = {c: result.get(c) for c in cols}
            if table == 'person':
                row['person_source_value'] = None
            ok, err = insert(con, table, row)
            if ok:
                print(f'  OK {path.name} -> {table}')
                results.append({'file': path.name, 'map': map_name, 'table': table, 'status': 'OK'})
                csv_rows.setdefault(table, []).append(row)
            else:
                is_server_dup = map_name.endswith('Server') and err and 'violates primary key constraint' in err
                status = 'SKIP' if is_server_dup else 'WARN'
                results.append({'file': path.name, 'map': map_name, 'table': table, 'status': status, 'detail': err})

    for path in sorted(fixture_dir.glob('*.json')):
        if path.name in processed:
            continue
        try:
            resource_type = json.loads(path.read_text()).get('resourceType', '?')
        except Exception:
            resource_type = '?'
        msg = f'No StructureMap for {resource_type} — no FML file to process this resource type'
        print(f'  SKIP {path.name}: {msg}')
        results.append({'file': path.name, 'map': '', 'table': '', 'status': 'SKIP', 'detail': msg})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures-dir', nargs='+', default=os.environ.get('FIXTURES_DIR', 'test_files').split(),
                        help='One or more fixture directories (default: test_files; also reads FIXTURES_DIR env var)')
    args = parser.parse_args()
    run(fixture_dirs=[SCRIPTS_DIR / d for d in args.fixtures_dir])

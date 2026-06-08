"""
Load all FHIR fixture JSON files through matchbox transforms and insert into
an OMOP CDM 5.4 DuckDB database.
"""

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
    transform_condition,
    transform_encounter,
    transform_immunization,
    transform_measurement,
    transform_medication,
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

FIXTURE_TRANSFORMS = [
    # pattern, transform_fn, table, map_name
    ('condition_*.json',      transform_condition,   'condition_occurrence', 'ConditionMap'),
    ('patient*.json',         transform_patient,     'person',               'PersonMap'),
    ('Patient-Pat-*.json',   transform_patient,     'person',               'PersonMap'),
    ('procedure_*.json',      transform_procedure,   'procedure_occurrence', 'ProcedureMap'),
    ('allergy_*.json',        transform_allergy,     'observation',          'AllergyMap'),
    ('encounter_*.json',      transform_encounter,   'visit_occurrence',     'EncounterVisitMap'),
    ('immunization_*.json',   transform_immunization,'drug_exposure',        'ImmunizationMap'),
    ('observation_weight_int.json', transform_measurement, 'measurement',    'MeasurementMap'),
    ('observation_temperature_int.json', transform_vital_signs, 'measurement', 'SimpleVitalSignsMap'),
    ('observation_smoking*.json', transform_observation, 'observation',      'ObservationMap'),
    ('medication_*.json',     transform_medication,  'drug_exposure',        'MedicationStatementMap'),
]

STATUS_COLOR = {
    'OK':         '#2d8a4e',
    'SUPPRESSED': '#888',
    'WARN':       '#c07a00',
    'SKIP':       '#c0392b',
}


def load_ddl(con):
    for name in [
        'OMOPCDM_duckdb_5.4_ddl.sql',
        'OMOPCDM_duckdb_5.4_primary_keys.sql',
        'OMOPCDM_duckdb_5.4_constraints.sql',
        'OMOPCDM_duckdb_5.4_indices.sql',
    ]:
        sql = (DDL_DIR / name).read_text()
        sql = sql.replace('@cdmDatabaseSchema.', '')
        for statement in sql.split(';'):
            lines = [l for l in statement.splitlines() if not l.strip().startswith('--')]
            statement = '\n'.join(lines).strip()
            if statement:
                try:
                    con.execute(statement)
                except (duckdb.CatalogException, duckdb.NotImplementedException):
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
            f'INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})',
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
                f'<a href="csv/{table}.csv" target="_blank">{n}&nbsp;rows</a>'
                f'&nbsp;<a href="csv/{table}.csv" download>&#8595;dl</a>'
            )
        else:
            csv_cell = ''
        rows_html += (
            f'<tr>'
            f'<td><a href="fixtures/{r["file"]}">{r["file"]}</a></td>'
            f'<td><a href="https://hl7.org/fhir/uv/omop/StructureMap-{r.get("map","")}.html" target="_blank"><code>{r.get("map","")}</code></a></td>'
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
        print(f'  CSV {out} ({len(rows)} rows)')
    print(f'CSV files written to {CSV_DIR}')


def run():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
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

    for pattern, transform_fn, table, map_name in FIXTURE_TRANSFORMS:
        paths = sorted(SCRIPTS_DIR.glob(pattern))
        for path in paths:
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
            ok, err = insert(con, table, row)
            if ok:
                print(f'  OK {path.name} -> {table}')
                results.append({'file': path.name, 'map': map_name, 'table': table, 'status': 'OK'})
                csv_rows.setdefault(table, []).append(row)
            else:
                results.append({'file': path.name, 'map': map_name, 'table': table, 'status': 'WARN', 'detail': err})

    con.close()
    print(f'Done. Database written to {DB_PATH}')
    write_csvs(csv_rows)
    write_report(results, csv_rows)


if __name__ == '__main__':
    run()

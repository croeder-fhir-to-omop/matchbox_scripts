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
import requests

from omop_to_csv import COLUMNS as OMOP_COLUMNS
from transforms import (
    SkipResource,
    transform_allergy,
    transform_bp_diastolic,
    transform_bp_panel,
    transform_bp_systolic,
    transform_condition,
    transform_encounter,
    transform_immunization,
    transform_measurement,
    transform_medication,
    transform_observation,
    transform_patient,
    transform_procedure,
    transform_vital_signs,
    # R5 variants
    transform_allergy_r5,
    transform_bp_diastolic_r5,
    transform_bp_panel_r5,
    transform_bp_systolic_r5,
    transform_condition_r5,
    transform_encounter_r5,
    transform_immunization_r5,
    transform_measurement_r5,
    transform_medication_r5,
    transform_observation_r5,
    transform_patient_r5,
    transform_procedure_r5,
    transform_vital_signs_r5,
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
    ('encounter_*.json',      transform_encounter,  'visit_occurrence',     'EncounterVisitMap'),

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
    ('allergy_*.json',        transform_allergy,    'observation',          'AllergyMap'),
    ('medicationstatement*.json', transform_medication, 'drug_exposure',        'MedicationMap'),
]

# R5 variant transforms — mirrors FIXTURE_TRANSFORMS but targets the R5 matchbox
# and uses R5-suffixed map names. Fixture file naming conventions are the same.
FIXTURE_TRANSFORMS_R5 = [
    ('patient*.json',         transform_patient_r5,       'person',               'PersonMap'),
    ('Patient-Pat-*.json',    transform_patient_r5,       'person',               'PersonMap'),
    ('encounter_*.json',      transform_encounter_r5,     'visit_occurrence',     'EncounterVisitMap'),
    ('condition_*.json',      transform_condition_r5,     'condition_occurrence', 'ConditionMap'),
    ('procedure_*.json',      transform_procedure_r5,     'procedure_occurrence', 'ProcedureMap'),
    ('immunization_*.json',   transform_immunization_r5,  'drug_exposure',        'ImmunizationMap'),
    ('observation_*weight*.json',    transform_measurement_r5, 'measurement',     'MeasurementMap'),
    ('observation_*creatinine*.json',transform_measurement_r5, 'measurement',     'MeasurementMap'),
    ('observation_*sodium*.json',    transform_measurement_r5, 'measurement',     'MeasurementMap'),
    ('observation_*NEG*.json',       transform_measurement_r5, 'measurement',     'MeasurementMap'),
    ('observation_*temp*.json',      transform_vital_signs_r5, 'measurement',     'SimpleVitalSignsMap'),
    ('observation_*heartrate*.json', transform_vital_signs_r5, 'measurement',     'SimpleVitalSignsMap'),
    ('observation_bp*.json',         transform_bp_panel_r5,    'measurement',     'BloodPressureVitalSignsMap'),
    ('observation_bp*.json',         transform_bp_systolic_r5, 'measurement',     'BloodPressureSystolicMap'),
    ('observation_bp*.json',         transform_bp_diastolic_r5,'measurement',     'BloodPressureDiastolicMap'),
    ('observation_*blood*.json',     transform_bp_panel_r5,    'measurement',     'BloodPressureVitalSignsMap'),
    ('observation_*blood*.json',     transform_bp_systolic_r5, 'measurement',     'BloodPressureSystolicMap'),
    ('observation_*blood*.json',     transform_bp_diastolic_r5,'measurement',     'BloodPressureDiastolicMap'),
    ('observation_smoking*.json',    transform_observation_r5, 'observation',     'ObservationMap'),
    ('allergy_*.json',        transform_allergy_r5,       'observation',          'AllergyMap'),
    ('medicationstatement*.json', transform_medication_r5, 'drug_exposure',       'MedicationMap'),
]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Load FHIR fixtures into OMOP DuckDB')
    parser.add_argument('--fixtures-dir', default=None,
                        help='Directory containing FHIR fixture JSON files')
    parser.add_argument('--fhir-version', choices=['r4', 'r5'], default='r4',
                        help='FHIR version to use for transforms (default: r4)')
    return parser.parse_args(argv)


def select_fixture_transforms(fhir_version: str):
    """Return the FIXTURE_TRANSFORMS list appropriate for the given FHIR version."""
    return FIXTURE_TRANSFORMS_R5 if fhir_version == 'r5' else FIXTURE_TRANSFORMS


# Fixtures whose failures are expected. When a WARN/ERROR occurs for a file in this
# set, the status is shown as XFAIL (expected failure) rather than WARN, so green
# runs are not obscured by known-bad test cases. The transform still runs and the
# actual error message is preserved.
EXPECTED_FAILURES = {
    # local institutional code — no standard OMOP mapping exists
    'condition_p3_local_unmapped.json',
    'procedure_p3_custom_concept_f2o-039.json',
    # no effective date on observation — tests date-required constraint
    'observation_p4_nodate_NEG_f2o-070.json',
    # identifier leak test: passes with numeric-ID approach — tracked as UPASS
    'condition_p4_identifier_leak_NEG_f2o-020.json',
    # intentionally missing subject
    'condition_p4_missing_subject_NEG_f2o-012.json',
    # not-done procedure (sample_fixtures and test_files)
    'procedure_p4_notdone_NEG_f2o-060.json',
    'procedure_not_done.json',
    # refuted condition
    'condition_refuted.json',
}

STATUS_COLOR = {
    'OK':         '#2d8a4e',
    'XFAIL':      '#5a7fa8',
    'UPASS':      '#a0522d',
    'NO_OUTPUT': '#888',
    'WARN':       '#c07a00',
    'SKIP':       '#888',
    'EXCEPT':     '#c0392b',
    'DBERROR':    '#7b0000',
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


def _extract_codings(obj, results=None):
    """Recursively extract all {system, code, display} dicts from FHIR resources.

    Handles both CodeableConcept (coding array) and bare Coding objects
    (e.g. Encounter.class, Quantity.system+code for unit lookups).
    """
    if results is None:
        results = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == 'coding' and isinstance(v, list):
                for coding in v:
                    if isinstance(coding, dict) and 'code' in coding:
                        results.append({
                            'system': coding.get('system', ''),
                            'code':   coding.get('code', ''),
                            'display': coding.get('display', ''),
                        })
            else:
                _extract_codings(v, results)
        # Also capture bare Coding/Quantity objects (have system+code but no coding sub-array)
        if 'code' in obj and 'system' in obj and 'coding' not in obj:
            results.append({
                'system':  obj['system'],
                'code':    obj['code'],
                'display': obj.get('display', ''),
            })
    elif isinstance(obj, list):
        for item in obj:
            _extract_codings(item, results)
    return results


def _codings_html(codings):
    if not codings:
        return ''
    parts = []
    for c in codings:
        sys_uri = c['system'] if c['system'] else '?'
        display = f' &mdash; {c["display"]}' if c.get('display') else ''
        parts.append(f'<code>{sys_uri}|{c["code"]}</code>{display}')
    return ('<br><span style="color:#555">Source codes: '
            + ' &nbsp; '.join(parts) + '</span>')


def _root_cause(detail, codings=None):
    if not detail:
        return ''
    if 'NOT NULL constraint' in detail:
        field = detail.split('.')[-1] if '.' in detail else detail
        interpretation = (f'<code>{field}</code> is NOT NULL but was not populated — '
                          f'translate() returned null (code not found on terminology server).')
        interpretation += _codings_html(codings)
    elif 'Could not convert string' in detail:
        import re
        m = re.search(r"string '([^']+)'", detail)
        val = m.group(1) if m else '?'
        interpretation = (f'StructureMap placed source code/label <code>{val}</code> '
                          f'directly into an integer concept_id field instead of translating it.')
        interpretation += _codings_html(codings)
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
    raw = f'<br><span style="color:#888;font-family:monospace">{detail}</span>'
    return interpretation + raw


def write_report(results, csv_rows=None, title=None):
    if title is None:
        title = 'FHIR &rarr; OMOP ETL Report'
    page_title = title.replace('&rarr;', '→').replace('&mdash;', '—')
    counts = {s: sum(1 for r in results if r['status'] == s) for s in STATUS_COLOR}
    csv_map = csv_rows or {}
    rows_html = ''
    for r in sorted(results, key=lambda r: r['file']):
        color = STATUS_COLOR.get(r['status'], '#000')
        detail = r.get('detail', '') or ''
        root = _root_cause(detail, r.get('codings'))
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
<title>{page_title}</title>
<style>
  body {{ font-family: sans-serif; margin: 2em; background: #f9f9f9; }}
  h1 {{ color: #333; }}
  .note {{ background:#fff8e1; border-left:4px solid #c07a00; padding:0.75em 1em; margin:1em 0; font-size:0.95em; }}
  .summary {{ margin: 1em 0; font-size: 1.1em; }}
  .legend {{ background:#fff; border:1px solid #ddd; border-radius:4px; padding:0.75em 1.25em; margin:1em 0; font-size:0.9em; }}
  .legend table {{ border-collapse:collapse; background:transparent; width:auto; }}
  .legend td {{ padding:3px 12px 3px 0; border:none; vertical-align:top; }}
  .legend .badge {{ font-weight:bold; min-width:6em; display:inline-block; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff; }}
  th {{ background: #333; color: #fff; padding: 8px 12px; text-align: left; }}
  td {{ padding: 6px 12px; border-bottom: 1px solid #ddd; vertical-align:top; }}
  tr:hover {{ background: #f0f0f0; }}
  code {{ background:#eee; padding:1px 4px; border-radius:3px; font-size:0.9em; }}
</style>
</head><body>
<h1>{title}</h1>
<p>Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
<div class="note">
  <strong>OMOP IG StructureMaps v{IG_VERSION} — concept mapping status:</strong>
  The StructureMaps call <code>translate()</code> with named IG ConceptMap URLs for
  clinical and administrative codes. <strong>enchilada</strong> (local FHIR R4 terminology
  server) resolves SNOMED, ICD-10-CM, LOINC, and RxNorm codes to OMOP concept_ids via
  the Athena vocabulary. IG ConceptMaps in matchbox handle administrative codes including
  gender, condition clinical status, allergy categories, immunization vaccine and route,
  vital signs and blood pressure LOINC codes.
  Remaining gaps: <code>unit_concept_id</code> (UCUM — no ConceptMap defined) and
  <code>drug_concept_id</code> for medication requests/statements.
</div>
<div class="note">
  <strong>CSV column note:</strong>
  The CSV file linked on each row contains <em>all rows</em> for that OMOP domain table
  across the entire fixture run — not just the row produced by the fixture on that line.
</div>
<div class="summary">{summary}</div>
<div class="legend">
  <strong>Status legend</strong>
  <table>
    <tr><td><span class="badge" style="color:#2d8a4e">OK</span></td><td>Transform succeeded; row inserted into OMOP table.</td></tr>
    <tr><td><span class="badge" style="color:#5a7fa8">XFAIL</span></td><td>Expected failure &mdash; transform ran and error was captured, but this fixture is a known-bad negative test. Failures here are intentional.</td></tr>
    <tr><td><span class="badge" style="color:#a0522d">UPASS</span></td><td>Unexpected pass &mdash; fixture is listed as an expected failure but the transform succeeded and produced a row. Needs review.</td></tr>
    <tr><td><span class="badge" style="color:#c07a00">WARN</span></td><td>Unexpected failure &mdash; transform ran but produced an error or empty result. Needs investigation.</td></tr>
    <tr><td><span class="badge" style="color:#888">SKIP</span></td><td>Resource structurally incompatible with the current server (e.g. R5 resource sent to R4 matchbox). Transform not attempted.</td></tr>
    <tr><td><span class="badge" style="color:#888">NO_OUTPUT</span></td><td>Transform returned no output (matchbox OperationOutcome or unrecognised resource type). No OMOP row produced.</td></tr>
    <tr><td><span class="badge" style="color:#c0392b">EXCEPT</span></td><td>Unhandled exception during transform &mdash; matchbox or parsing error threw before any DB insert was attempted.</td></tr>
    <tr><td><span class="badge" style="color:#7b0000">DBERROR</span></td><td>Primary key constraint violation on insert &mdash; row conflicts with an existing record in the OMOP table.</td></tr>
  </table>
</div>
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


def run(fixture_dirs=None, fhir_version='r4'):
    if fixture_dirs is None:
        fixture_dirs = [DEFAULT_FIXTURES_DIR]
    elif isinstance(fixture_dirs, Path):
        fixture_dirs = [fixture_dirs]

    fixture_transforms = select_fixture_transforms(fhir_version)

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
        _load_fixture_dir(con, fixture_dir, results, csv_rows, fixture_transforms)

    con.close()
    print(f'Done. Database written to {DB_PATH}')
    write_csvs(csv_rows)
    dir_names = ' '.join(Path(d).name for d in fixture_dirs)
    fixture_label = 'Sample Fixtures' if 'sample' in dir_names else 'Test Files'
    report_title = f'FHIR {fhir_version.upper()} &rarr; OMOP ETL Report &mdash; {fixture_label}'
    write_report(results, csv_rows, title=report_title)


def _load_fixture_dir(con, fixture_dir, results, csv_rows, fixture_transforms=None):
    if fixture_transforms is None:
        fixture_transforms = FIXTURE_TRANSFORMS
    processed = set()
    for pattern, transform_fn, table, map_name in fixture_transforms:
        paths = sorted(fixture_dir.glob(pattern))
        for path in paths:
            processed.add(path.name)
            resource = json.loads(path.read_text())
            codings = _extract_codings(resource)
            try:
                result = transform_fn(resource)
            except SkipResource as e:
                msg = str(e)
                print(f'  SKIP {path.name}: {msg}', file=sys.stderr)
                results.append({'file': path.name, 'map': map_name, 'table': table, 'status': 'SKIP', 'detail': msg, 'codings': codings})
                continue
            except Exception as e:
                msg = str(e).split('\n')[0]
                print(f'  EXCEPT {path.name}: {msg}', file=sys.stderr)
                status = 'XFAIL' if path.name in EXPECTED_FAILURES else 'EXCEPT'
                results.append({'file': path.name, 'map': map_name, 'table': table, 'status': status, 'detail': msg, 'codings': codings})
                continue
            if result is None:
                print(f'  NO_OUTPUT {path.name}')
                results.append({'file': path.name, 'map': map_name, 'table': table, 'status': 'NO_OUTPUT'})
                continue
            resource_type = result.get('resourceType')
            cols = OMOP_COLUMNS.get(resource_type)
            if cols is None:
                msg = f'unknown resourceType {resource_type!r}'
                print(f'  SKIP {path.name}: {msg}', file=sys.stderr)
                results.append({'file': path.name, 'map': map_name, 'table': table, 'status': 'SKIP', 'detail': msg, 'codings': codings})
                continue
            row = {c: result.get(c) for c in cols}
            if table == 'person':
                row['person_source_value'] = None
            ok, err = insert(con, table, row)
            if ok:
                if path.name in EXPECTED_FAILURES:
                    status = 'UPASS'
                    print(f'  UPASS {path.name} -> {table} (expected to fail but passed)')
                else:
                    status = 'OK'
                    print(f'  OK {path.name} -> {table}')
                results.append({'file': path.name, 'map': map_name, 'table': table, 'status': status})
                csv_rows.setdefault(table, []).append(row)
            else:
                if path.name in EXPECTED_FAILURES:
                    status = 'XFAIL'
                elif err and 'violates primary key constraint' in err:
                    status = 'DBERROR'
                else:
                    status = 'WARN'
                results.append({'file': path.name, 'map': map_name, 'table': table, 'status': status, 'detail': err, 'codings': codings})

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
    _args = parse_args()
    _fixtures_dir = _args.fixtures_dir or os.environ.get('FIXTURES_DIR', 'test_files')
    _fixture_dirs = [SCRIPTS_DIR / d for d in _fixtures_dir.split()] if isinstance(_fixtures_dir, str) else [SCRIPTS_DIR / _fixtures_dir]
    run(fixture_dirs=_fixture_dirs, fhir_version=_args.fhir_version)

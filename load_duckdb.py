"""
Load all FHIR fixture JSON files through matchbox transforms and insert into
an OMOP CDM 5.4 DuckDB database.
"""

import json
import os
import sys
from glob import glob
from pathlib import Path

import duckdb

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

FIXTURE_TRANSFORMS = [
    ('condition_*.json',      transform_condition,   'condition_occurrence'),
    ('patient*.json',         transform_patient,     'person'),
    ('procedure_*.json',      transform_procedure,   'procedure_occurrence'),
    ('allergy_*.json',        transform_allergy,     'observation'),
    ('encounter_*.json',      transform_encounter,   'visit_occurrence'),
    ('immunization_*.json',   transform_immunization,'drug_exposure'),
    ('observation_weight_int.json', transform_measurement, 'measurement'),
    ('observation_temperature_int.json', transform_vital_signs, 'measurement'),
    ('observation_smoking*.json', transform_observation, 'observation'),
    ('medication_*.json',     transform_medication,  'drug_exposure'),
]


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
            statement = statement.strip()
            if statement and not statement.startswith('--'):
                try:
                    con.execute(statement)
                except duckdb.CatalogException:
                    pass


def insert(con, table, row):
    if not row:
        return
    cols = [k for k, v in row.items() if v != '' and v is not None]
    vals = [row[c] for c in cols]
    placeholders = ', '.join(['?'] * len(cols))
    col_list = ', '.join(cols)
    con.execute(
        f'INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})',
        vals,
    )


def run():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = duckdb.connect(DB_PATH)

    print('Loading OMOP CDM 5.4 schema...')
    load_ddl(con)

    for pattern, transform_fn, table in FIXTURE_TRANSFORMS:
        paths = sorted(SCRIPTS_DIR.glob(pattern))
        for path in paths:
            resource = json.loads(path.read_text())
            try:
                result = transform_fn(resource)
            except Exception as e:
                print(f'  SKIP {path.name}: {e}', file=sys.stderr)
                continue
            if result is None:
                print(f'  SUPPRESSED {path.name}')
                continue
            insert(con, table, result)
            print(f'  OK {path.name} -> {table}')

    con.close()
    print(f'Done. Database written to {DB_PATH}')


if __name__ == '__main__':
    run()

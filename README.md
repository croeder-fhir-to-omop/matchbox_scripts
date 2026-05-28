# matchbox_scripts

Python scripts and sample FHIR fixtures for the FHIR→OMOP pipeline. Used directly by `jupyter_docker` (interactive exploration) and `dqd_docker` (automated ETL + Data Quality Dashboard).

Part of the [croeder-fhir-to-omop](https://github.com/croeder-fhir-to-omop) FHIR→OMOP pipeline:

| Repo | Role |
|---|---|
| [matchbox](https://github.com/croeder-fhir-to-omop/matchbox) | FHIR server with OMOP IG (fork of ahdis/matchbox) |
| [matchbox_docker](https://github.com/croeder-fhir-to-omop/matchbox_docker) | Docker config and IGs for matchbox |
| **[matchbox_scripts](https://github.com/croeder-fhir-to-omop/matchbox_scripts)** | **Transform functions, ETL script, and FHIR fixtures ← you are here** |
| [jupyter_docker](https://github.com/croeder-fhir-to-omop/jupyter_docker) | Interactive Jupyter notebook environment |
| [dqd_docker](https://github.com/croeder-fhir-to-omop/dqd_docker) | Automated ETL + OHDSI Data Quality Dashboard |

## Main scripts

| Script | Description |
|---|---|
| `transforms.py` | One `transform_*()` function per FHIR resource type; each calls matchbox `$transform` and returns an OMOP-shaped dict |
| `load_duckdb.py` | Runs all transforms against the sample fixtures and loads results into a DuckDB OMOP CDM 5.4 database; writes an HTML ETL report |
| `omop_to_csv.py` | Converts a single transform result (JSON) to a CSV row; supports ConditionOccurrence, Person, ProcedureOccurrence, VisitOccurrence, DrugExposure, Measurement, Observation |

## Sample fixtures

FHIR resource JSON files paired with the transform that processes them:

| Fixture(s) | Transform | OMOP table |
|---|---|---|
| `condition_*.json` | `transform_condition` | `condition_occurrence` |
| `patient.json` | `transform_patient` | `person` |
| `procedure_*.json` | `transform_procedure` | `procedure_occurrence` |
| `allergy_peanut.json` | `transform_allergy` | `observation` |
| `encounter_outpatient.json` | `transform_encounter` | `visit_occurrence` |
| `immunization_flu.json` | `transform_immunization` | `drug_exposure` |
| `observation_weight_int.json` | `transform_measurement` | `measurement` |
| `observation_temperature_int.json` | `transform_vital_signs` | `measurement` |
| `observation_smoking*.json` | `transform_observation` | `observation` |
| `medication_aspirin.json` | `transform_medication` | `drug_exposure` |

## Running transforms manually

Start matchbox (see [matchbox_docker](https://github.com/croeder-fhir-to-omop/matchbox_docker)), then call any of the paired shell scripts:

```bash
bash transform_condition_fever.sh
bash transform_condition.sh       # condition_hypertension.json
bash patient.sh
```

Output is a JSON dict in FHIR resource form with OMOP column names as keys.

### Convert output to CSV

Pipe a transform directly:

```bash
bash transform_condition_fever.sh | python3 omop_to_csv.py
```

Accumulate multiple records:

```bash
bash transform_condition_fever.sh | python3 omop_to_csv.py                   > conditions.csv
bash transform_condition.sh       | python3 omop_to_csv.py --no-header >> conditions.csv
```

Or convert a saved JSON file:

```bash
python3 omop_to_csv.py condition_fever_output.json
```

### Utility scripts

| Script | Description |
|---|---|
| `check_ig_loaded.sh` | Confirms the OMOP IG is loaded in matchbox |
| `check_operations.sh` | Lists available FHIR operations |
| `check_structure_maps.sh` | Lists loaded StructureMaps |
| `upload_personmap.sh` | Uploads `PersonMap.fml` to matchbox |

## Links

- [matchbox](https://github.com/croeder-fhir-to-omop/matchbox) — fork of [ahdis/matchbox](https://github.com/ahdis/matchbox)
- [HL7 FHIR-to-OMOP IG](https://hl7.org/fhir/uv/omop/) — defines the 11 StructureMaps used here
- [Echidna terminology server](https://echidna.fhir.org/) — OMOP vocabulary for concept lookups, configured in matchbox
- [OHDSI Athena](https://athena.ohdsi.org/search-terms/start) — look up OMOP concept IDs

# matchbox_scripts

Python scripts and sample FHIR fixtures for the FHIR→OMOP pipeline. Used directly by `jupyter_docker` (interactive exploration) and `dqd_docker` (automated ETL + Data Quality Dashboard).

Part of the [croeder-fhir-to-omop](https://github.com/croeder-fhir-to-omop) FHIR→OMOP pipeline:

| Repo | Role |
|---|---|
| [fhir-omop-ig](https://github.com/croeder-fhir-to-omop/fhir-omop-ig) | HL7 FHIR-to-OMOP Implementation Guide — StructureMaps and ConceptMaps |
| [matchbox](https://github.com/croeder-fhir-to-omop/matchbox) | FHIR server with OMOP IG (fork of ahdis/matchbox) |
| [matchbox_docker](https://github.com/croeder-fhir-to-omop/matchbox_docker) | Docker config and IGs for matchbox |
| **[matchbox_scripts](https://github.com/croeder-fhir-to-omop/matchbox_scripts)** | **Transform functions, ETL script, and FHIR fixtures ← you are here** |
| [jupyter_docker](https://github.com/croeder-fhir-to-omop/jupyter_docker) | Interactive Jupyter notebook environment |
| [dqd_docker](https://github.com/croeder-fhir-to-omop/dqd_docker) | Automated ETL + OHDSI Data Quality Dashboard |
| [enchilada](https://github.com/croeder-fhir-to-omop/enchilada) | Local OMOP-backed FHIR terminology server |

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

## Building images

`build.py` is the build pipeline for the default r5/1.0.0 stack. It manages the full sequence: IG build → matchbox JAR → Docker image → publish.

```bash
python3 build.py                      # full pipeline; builds from HL7/fhir-omop-ig upstream/main → croeder/matchbox:latest
python3 build.py ig docker release    # IG + image + push only
python3 build.py --ig-source main ig docker release    # fork main → croeder/matchbox:main
python3 build.py --ig-source <branch> ig docker        # fork branch → croeder/matchbox:<branch>
python3 build.py --tx-server n/a ig                    # skip terminology validation during IG build
```

Every built image carries labels identifying the IG source and commit:

```bash
docker inspect croeder/matchbox:latest | python3 -c "
import json, sys
labels = json.load(sys.stdin)[0]['Config']['Labels']
for k, v in labels.items():
    if k.startswith('fhir-omop-ig'):
        print(f'{k}: {v}')
"
```

```
fhir-omop-ig.source:     upstream
fhir-omop-ig.commit:     1ec215b3f...
fhir-omop-ig.build-date: 2026-06-23T19:05:00Z
```

See [matchbox_docker](https://github.com/croeder-fhir-to-omop/matchbox_docker) for the Dockerfile and compose files used by `build.py`.

## How the ETL pipeline drives fixtures through StructureMaps

`load_duckdb.py` contains a dispatch table, `FIXTURE_TRANSFORMS`, where each row is:

```
(glob pattern,  transform function,   OMOP table,           StructureMap name)
('condition_*.json', transform_condition, 'condition_occurrence', 'ConditionMap')
```

For each row, every fixture file whose name matches the glob is passed to the transform function, which calls matchbox's `$transform` endpoint using the named StructureMap. The result is an OMOP-shaped dict that `load_duckdb.py` inserts into the named OMOP table. There is one transform function per StructureMap — not one per OMOP table, since multiple StructureMaps can target the same table (for example, `MeasurementMap`, `SimpleVitalSignsMap`, `BloodPressurePanelMap`, `BloodPressureSystolicMap`, and `BloodPressureDiastolicMap` all write to `measurement`). A single fixture file can also match multiple rows — blood pressure files are intentionally passed through three separate StructureMaps to produce panel, systolic, and diastolic records.

## Adding FHIR fixtures

Fixtures are FHIR resource JSON files stored in `matchbox_scripts/`. The two built-in sets serve different purposes: `test_files_r5/` contains simple single-resource files for exercising specific StructureMap scenarios; `sample_fixtures_r5/` contains a linked multi-patient set for broader regression coverage. You can add files to either set or bring your own data entirely.

### Using your own FHIR data

To run the pipeline against your own FHIR resources without modifying the built-in fixture sets, drop your JSON files into `matchbox_scripts/sample_fixtures_r5/` — any file whose name matches an existing glob pattern in `FIXTURE_TRANSFORMS_R5` will be picked up automatically. Name files after the resource type they contain (e.g. `condition_*.json`, `observation_*.json`) to match the existing patterns. The ETL report on port 8088 will include your files alongside the built-in ones.

If you want a completely separate directory, you would need to edit `load_duckdb.py` to point at it — there is no command-line argument for this yet.

### Existing StructureMaps

Add a JSON file whose name matches an existing glob pattern (e.g. `condition_diabetes.json`, `observation_bp_standing.json`) — no code changes needed. The glob patterns are defined in `FIXTURE_TRANSFORMS` in `load_duckdb.py`.

- **Option B / Jupyter**: Drop the file into `matchbox_scripts/` on your host — it appears immediately inside the container. No restart needed. Commit and push to persist for others.
- **Option A / automated ETL**: Add the file to `matchbox_scripts/`, then rebuild: `docker compose -f dqd_docker/docker-compose.yml -f dqd_docker/docker-compose.dev.yml up --build`.

### New StructureMaps

To incorporate a new StructureMap (e.g. for Death or Device):

1. Add the FHIR JSON fixture to `matchbox_scripts/`
2. Add a `transform_<type>()` function to `transforms.py` that calls `_call_r5(resource, 'YourMapName')`
3. Add a row to `FIXTURE_TRANSFORMS_R5` in `load_duckdb.py` with the glob pattern, transform function, target OMOP table, and StructureMap name
4. Commit and push, then rebuild for Option A

## Working with the Implementation Guide

The `croeder/matchbox:latest` image has `hl7.fhir.uv.omop#1.0.0` baked in. If you are working on the IG itself — editing StructureMaps or ConceptMaps in `fhir-omop-ig/` — you need to build a new IG package and get it into matchbox. There are two paths depending on whether you want a quick local test or a published image.

### Step 1 — Build the IG

The IG is built using the [bonfhir ig-toolbox](https://github.com/bonfhir/ig-toolbox) Docker container, which wraps the FHIR publisher JAR. The `build.py ig` step handles this automatically — it runs the bonfhir container against `fhir-omop-ig/`, calls the publisher with `tx.fhir.org` as the build-time terminology server (this is separate from the runtime terminology server used by the pipeline), then copies the output into place and strips transitive package dependencies.

Clone `fhir-omop-ig` and `matchbox_scripts` side by side, then:

```bash
git clone https://github.com/croeder-fhir-to-omop/fhir-omop-ig
git clone https://github.com/croeder-fhir-to-omop/matchbox_scripts
cd matchbox_scripts
python3 build.py ig
```

This produces `fhir-omop-ig/output/package.tgz` and copies it to `matchbox_docker/igs/hl7.fhir.uv.omop-1.0.0.tgz`, ready for the Docker build.

### Path A — Local run (no image rebuild)

The published matchbox image loads configs in order:

```
/defaults/application.yaml  →  /config/application.yaml  (optional override)
```

Mount your new IG package and a config override into the running container — no rebuild needed.

**1. Write `config/application.yaml`** in your working directory:

```yaml
hapi:
  fhir:
    implementationguides:
      fhiromop:
        name: hl7.fhir.uv.omop
        version: <version>
        url: file:///igs/hl7.fhir.uv.omop-<version>.tgz

matchbox:
  fhir:
    context:
      igsPreloaded:
        - hl7.fhir.uv.omop#<version>
```

**2. Add volume mounts** to your `docker-compose.yml` under the `matchbox` service:

```yaml
volumes:
  - matchbox-db:/database
  - ./matchbox_docker/igs:/igs:ro
  - ./config:/config:ro
```

**3. Start** (use `down -v` first to clear the cached H2 database so matchbox reloads the IG from scratch):

```bash
docker compose down -v
docker compose up
```

### Path B — Bake into the image and publish

Clone `matchbox_docker` alongside your other repos, then use the build script:

```bash
git clone https://github.com/croeder-fhir-to-omop/matchbox_docker
git clone https://github.com/croeder-fhir-to-omop/matchbox_scripts

cd matchbox_scripts

# Default: builds from HL7/fhir-omop-ig upstream/main → croeder/matchbox:latest
python3 build.py ig mvn docker release

# Fork main: builds from croeder-fhir-to-omop/fhir-omop-ig main → croeder/matchbox:main
python3 build.py --ig-source main ig mvn docker release

# Branch: builds from a named fork branch → croeder/matchbox:<branch>
python3 build.py --ig-source fix-translate-rule-names ig docker release
```

The build script checks out the requested source in `fhir-omop-ig`, builds the IG and image, then restores the original branch. Anyone who then does `docker compose pull` or runs the curl command fresh gets the updated image.

## Extending or replacing the conversion engine

### Replacing matchbox

`transforms.py` is the only file that knows about matchbox. Every `transform_*()` function takes a FHIR resource dict and returns either `None` (to suppress the resource) or an OMOP-shaped dict that is itself in FHIR resource form: a `resourceType` field (e.g. `"ConditionOccurrence"`) plus OMOP column names as the remaining keys. That `resourceType` is how `load_duckdb.py` looks up the correct column list in `omop_to_csv.COLUMNS` and knows which fields to extract before inserting into DuckDB.

To swap in a different engine, rewrite `transforms.py` — replace the `_call()` helper to hit a different HTTP endpoint, rewrite individual functions to convert locally, or replace the file entirely. As long as the return value keeps this FHIR-envelope shape, nothing else in the pipeline needs to change.

### If your engine produces CSV

If a replacement engine produces plain CSV row strings instead of FHIR-shaped dicts, three things break and need updating:

- **`load_duckdb.py`**: the `resourceType` dispatch disappears; key off the table name already present in each `FIXTURE_TRANSFORMS` entry instead
- **`omop_to_csv.COLUMNS`**: currently keyed by PascalCase resourceType (e.g. `"ConditionOccurrence"`); would need rekeying by snake_case table name (e.g. `"condition_occurrence"`)
- **Parsing**: the CSV string would need to be parsed into a column→value dict before the existing `insert()` function can use it

## Links

- [matchbox](https://github.com/croeder-fhir-to-omop/matchbox) — fork of [ahdis/matchbox](https://github.com/ahdis/matchbox)
- [HL7 FHIR-to-OMOP IG](https://hl7.org/fhir/uv/omop/) — defines the 11 StructureMaps used here
- [enchilada](https://github.com/croeder-fhir-to-omop/enchilada) — local OMOP-backed terminology server (default); [echidna](https://echidna.fhir.org/) is a public alternative — see the [org README](https://github.com/croeder-fhir-to-omop) for configuration
- [OHDSI Athena](https://athena.ohdsi.org/search-terms/start) — look up OMOP concept IDs

## License

Licensed under the [Apache License 2.0](./LICENSE). Copyright 2026 Christophe Roeder.

This repository includes test fixtures that reference clinical terminology content (LOINC, SNOMED CT, RxNorm, ICD-10-CM, CVX, UCUM). See [NOTICES.md](https://github.com/croeder-fhir-to-omop/.github/blob/main/profile/NOTICES.md) for third-party vocabulary license details.

See the [organization README](https://github.com/croeder-fhir-to-omop) for running the pipeline end-to-end.

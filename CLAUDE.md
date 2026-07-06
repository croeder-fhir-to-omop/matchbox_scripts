
Project-wide rules for all croeder-fhir-to-omop repos: @../.github/CLAUDE.md

## Build & Deploy

`python3 build.py [steps]` — simple r5/1.0.0 pipeline. No flags needed.
Steps: `ig` (rebuild IG), `mvn` (rebuild matchbox JAR), `docker` (rebuild matchbox image),
`restart` (wipe + restart stack), `etl` (re-run ETL, open reports), `test` (integration tests),
`release` (build + push images), `start` (start stack), `stop` (stop stack).
Default (no args): `ig mvn docker restart etl test`.

`python3 build_profiles.py [--fhir-version r4|r5] [--ig-version 1.0.0|1.0.1] [steps]` — multi-stack pipeline.
Use this when working with stacks other than the default r5/1.0.0.

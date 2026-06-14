
This is work for R4 FHIR


  ## Build & Deploy
  `python3 build.py [steps]` — orchestrates the full pipeline.
  Steps: `ig` (rebuild IG), `docker` (rebuild matchbox image), `restart` (wipe + restart containers),
  `etl` (re-run ETL, open reports), `test` (integration tests), `mvn` (rebuild matchbox JAR).
  Default: `ig docker restart test`. Staleness checks auto-run prerequisites.



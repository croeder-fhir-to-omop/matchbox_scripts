# matchbox_scripts
This is a repo of scripts to test the translation of a few FHIR
resources to other resources that look like OMOP tables. It uses
a docker image, croeder/matchbox:latest, that sets up a product
called matchbox, that itself is deployable server built from HAPI-FHIR.
The matchbox server knows about the Vulcan FHIR-to-OMOP IG and loads 
it for the structure maps. It also knows about the Echnica terminology
server that has the OHDSI/OMOP vocabulary loaded in it for matchbox'x use.

## Getting Started Locally
These instructions should guide you to running these tools 
on a local laptop. Terminology mapping will call out to the 
FHIR terminology server. Some experience with bash will be useful.
 
- Install Docker and Git
  - install  docker or docker desktop   
    - https://www.docker.com/products/docker-desktop/
  - install git 
    - include git bash if on windows
    - https://git-scm.com/install/

- Git Clone this repo
  - bash> git clone https://github.com/croeder/matchbox_scripts

- Start the matchbox server in Docker
  - easily from a git bash prompt:
    - bash> docker run -p 8080:8080 croeder/matchbox:latest
  - perhaps also from the Docker Desktop UI (TBD)
    - Search for croeder/matchbox:latest
    - Start it
      - expose the port 8080 as 8080

- Run Scripts to Exercise the Mapping
The scripts are paired with a JSON file containing a FHIR resource.
They each curl into the server to transform the FHIR to OMOP. The 
output is a FHIR resource, but in the shape of an OMOP table.
  - payload.sh, patient.json
  - transform_condition_fever.sh,  condition_fever.json
  - transform_condition.sh, condition_hypertension.json

- Convert Transform Output to CSV
`omop_to_csv.py` reads the JSON output of a transform script and emits
a CSV row with the full set of OMOP column headers. It requires Python 3
and dispatches automatically on `resourceType` (currently supports
`ConditionOccurrence` and `Person`).

  Pipe a single transform directly:
  ```bash
  bash transform_condition_fever.sh | python3 omop_to_csv.py
  ```

  Accumulate multiple records into one file:
  ```bash
  bash transform_condition_fever.sh | python3 omop_to_csv.py                   > conditions.csv
  bash transform_condition.sh       | python3 omop_to_csv.py --no-header >> conditions.csv
  ```

  Or convert a saved JSON file:
  ```bash
  python3 omop_to_csv.py condition_fever_output.json
  ```

## Getting Started on a Jupyter notebook on Google Colab (TBD)
Running a public server involves taking on provisioning and deploying
the hardware resources and restricted access to known and well behaved
actors. With the matchbox server available, it would be possible to 
set up a Jupyter notebook on Google collab where the shell scripts could
be run. The server above is doing the heavy lifting.

## Links

- https://github.com/croeder/matchbox
  This is a fork that resolves some issues I had, though I have not
  worked with the matchbox folks on these. They may have other or 
  better solutions.

- https://hub.docker.com/repository/docker/croeder/matchbox/general
  This is the dockerized version of my matchbox fork.

- https://github.com/croeder/matchbox_scripts
  This repository that has some scripts and FHIR data as json files
  to use the structure maps in the FHIR-to-OMOP IG

- https://build.fhir.org/ig/HL7/fhir-omop-ig/en/
  The HL7 Vulcan FHIR to OMOP IG.

- https://echidna.fhir.org/
  The Echidna terminology server. This has been loaded with recent
  vocabulary from OHDSI by way of their Athena tool and is used to
  map terms or concepts in the FHIR resource data to the OMOP vocabulary
  for use in the output OMOP table rows.

- https://athena.ohdsi.org/search-terms/start
  The OHDSI Athena site. You can lookup a term's mapping here, as well
  as arrange a download of (nearly) all the terms for local use.

## TBD
- more fine-grained detail in these instructions


## MISC other scripts and data
- check_ig_loaded.sh*
- check_operations.sh*
- check_structure_maps.sh*
- run_via_docker.sh*
- transform.json
- transform.sh*
- transform_0.sh*
- transform_a.sh*
- upload_personmap.sh

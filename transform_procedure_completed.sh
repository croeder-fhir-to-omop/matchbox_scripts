#!/usr/bin/env bash
# Transform a completed Procedure — should produce an OMOP procedure_occurrence row

BASE_URL="http://localhost:8080/matchboxv3/fhir"
MAP_URL="http://hl7.org/fhir/uv/omop/StructureMap/ProcedureMap"

curl -s -X POST "${BASE_URL}/StructureMap/\$transform?source=${MAP_URL}" \
  -H "Content-Type: application/fhir+json" \
  -H "Accept: application/fhir+json" \
  -d @procedure_completed.json |\
python3 omop_to_csv.py

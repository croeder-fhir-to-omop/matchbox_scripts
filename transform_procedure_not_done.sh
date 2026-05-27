#!/usr/bin/env bash
# Transform a not-done Procedure — status=not-done should suppress OMOP output

BASE_URL="http://localhost:8080/matchboxv3/fhir"
MAP_URL="http://hl7.org/fhir/uv/omop/StructureMap/ProcedureMap"

curl -s -X POST "${BASE_URL}/StructureMap/\$transform?source=${MAP_URL}" \
  -H "Content-Type: application/fhir+json" \
  -H "Accept: application/fhir+json" \
  -d @procedure_not_done.json |\
python3 omop_to_csv.py

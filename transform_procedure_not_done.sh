#!/usr/bin/env bash
# Transform a not-done Procedure — status=not-done should suppress OMOP output

if [ "$1" = "--standalone" ]; then
  BASE_URL="http://localhost:8080/matchboxv3/fhir"
else
  BASE_URL="${MATCHBOX_URL:-http://matchbox:8080}/matchboxv3/fhir"
fi
MAP_URL="http://hl7.org/fhir/uv/omop/StructureMap/ProcedureMap"

curl -s -X POST "${BASE_URL}/StructureMap/\$transform?source=${MAP_URL}" \
  -H "Content-Type: application/fhir+json" \
  -H "Accept: application/fhir+json" \
  -d @procedure_not_done.json |\
python3 omop_to_csv.py

#!/usr/bin/env bash
# Pattern B: reference map by canonical URL (source query param), body is the resource directly

FIXTURES_DIR="${FIXTURES_DIR:-test_files}"

if [ "$1" = "--standalone" ]; then
  BASE_URL="http://localhost:8080/matchboxv3/fhir"
else
  BASE_URL="${MATCHBOX_URL:-http://matchbox:8080}/matchboxv3/fhir"
fi
MAP_URL="http://hl7.org/fhir/uv/omop/StructureMap/PersonMap"

curl -s -X POST "${BASE_URL}/StructureMap/\$transform?source=${MAP_URL}" \
  -H "Content-Type: application/fhir+json" \
  -H "Accept: application/fhir+json" \
  -d @"${FIXTURES_DIR}/patient.json" |\
python3 omop_to_csv.py

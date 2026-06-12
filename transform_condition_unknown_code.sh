#!/usr/bin/env bash
# Transform a Condition with a bogus SNOMED code — should this produce an OMOP row?

FIXTURES_DIR="${FIXTURES_DIR:-test_files}"

if [ "$1" = "--standalone" ]; then
  BASE_URL="http://localhost:8080/matchboxv3/fhir"
else
  BASE_URL="${MATCHBOX_URL:-http://matchbox:8080}/matchboxv3/fhir"
fi
MAP_URL="http://hl7.org/fhir/uv/omop/StructureMap/ConditionMap"

curl -s -X POST "${BASE_URL}/StructureMap/\$transform?source=${MAP_URL}" \
  -H "Content-Type: application/fhir+json" \
  -H "Accept: application/fhir+json" \
  -d @"${FIXTURES_DIR}/condition_unknown_code.json" |\
python3 omop_to_csv.py

#!/usr/bin/env bash
# Pattern B: reference map by canonical URL (source query param), body is the resource directly

BASE_URL="http://localhost:8080/matchboxv3/fhir"
MAP_URL="http://hl7.org/fhir/uv/omop/StructureMap/PersonMap"

curl -s -X POST "${BASE_URL}/StructureMap/\$transform?source=${MAP_URL}" \
  -H "Content-Type: application/fhir+json" \
  -H "Accept: application/fhir+json" \
  -d @patient.json

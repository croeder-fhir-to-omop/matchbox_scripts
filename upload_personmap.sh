#!/usr/bin/env bash
# Upload PersonMap.fml to the server so it can be referenced by URL in $transform

BASE_URL="http://localhost:8080/matchboxv3/fhir"

curl -s -X POST "${BASE_URL}/StructureMap" \
  -H "Content-Type: text/fhir-mapping" \
  -H "Accept: application/fhir+json" \
  --data-binary @PersonMap.fml

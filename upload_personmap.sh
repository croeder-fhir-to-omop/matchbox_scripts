#!/usr/bin/env bash
# Upload PersonMap.fml to the server so it can be referenced by URL in $transform

if [ "$1" = "--standalone" ]; then
  BASE_URL="http://localhost:8080/matchboxv3/fhir"
else
  BASE_URL="${MATCHBOX_URL:-http://matchbox:8080}/matchboxv3/fhir"
fi

curl -s -X POST "${BASE_URL}/StructureMap" \
  -H "Content-Type: text/fhir-mapping" \
  -H "Accept: application/fhir+json" \
  --data-binary @PersonMap.fml

#!/usr/bin/env bash

if [ "$1" = "--standalone" ]; then
  BASE_URL="http://localhost:8080/matchboxv3/fhir"
else
  BASE_URL="${MATCHBOX_URL:-http://matchbox:8080}/matchboxv3/fhir"
fi

curl -X POST "${BASE_URL}/StructureMap/$transform" \
  -H "Content-Type: application/fhir+json" \
  -d @payload.json
#curl -X POST "http://localhost:8080/matchboxv3/fhir/$transform" \
#  -H "Content-Type: application/fhir+json" \
#  -d @transform.json



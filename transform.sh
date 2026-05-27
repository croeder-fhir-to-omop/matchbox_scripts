#!/usr/bin/env bash


#    "diagnostics": "HAPI-0450: Failed to parse request body as JSON resource. Error was: HAPI-1814: Incorrect resource type found, expected \"StructureMap\" but found \"Parameters\""
if [ "$1" = "--standalone" ]; then
  BASE_URL="http://localhost:8080/matchboxv3/fhir"
else
  BASE_URL="${MATCHBOX_URL:-http://matchbox:8080}/matchboxv3/fhir"
fi

curl -X POST "${BASE_URL}/StructureMap/$transform" \
  -H "Content-Type: application/fhir+json" \
  -d @transform.json

#     "diagnostics": "HAPI-0287: This is the base URL of FHIR server. Unable to handle this request, as it does not contain a resource type or operation name."
#curl -X POST "http://localhost:8080/matchboxv3/fhir/$transform" \
#  -H "Content-Type: application/fhir+json" \
#  -d @transform.json



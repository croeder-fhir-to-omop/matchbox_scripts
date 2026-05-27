#!/usr/bin/env bash
if [ "$1" = "--standalone" ]; then
  BASE_URL="http://localhost:8080"
else
  BASE_URL="${MATCHBOX_URL:-http://matchbox:8080}"
fi

curl -X 'GET'   "${BASE_URL}/matchboxv3/fhir/ImplementationGuide?_content=omop"   -H 'accept: application/fhir+json'

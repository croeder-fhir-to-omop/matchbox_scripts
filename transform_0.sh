#!/usr/bin/env bash

curl -X POST "http://localhost:8080/matchboxv3/fhir/StructureMap/$transform" \
  -H "Content-Type: application/fhir+json" \
  -d @payload.json
#curl -X POST "http://localhost:8080/matchboxv3/fhir/$transform" \
#  -H "Content-Type: application/fhir+json" \
#  -d @transform.json



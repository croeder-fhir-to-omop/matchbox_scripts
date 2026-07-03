#!/usr/bin/env bash

curl -X GET "https://echidna.fhir.org/r4/metadata?mode=terminology" \
  -H "Accept: application/fhir+json"

echo "" 
echo "====================================="

curl -X GET "https://echidna.fhir.org/r4/CodeSystem" \
  -H "Accept: application/fhir+json"

echo "" 
echo "====================================="

curl -X GET "https://echidna.fhir.org/r4/metadata" \
  -H "Accept: application/fhir+json" > echidna_capabiliy.json


#!/usr/bin/env bash
# Translate a nonexistent SNOMED code to demonstrate a failed lookup

BASE_URL="https://echidna.fhir.org/r4"
SNOMED_CODE="0000001"
SNOMED_SYSTEM="http://snomed.info/sct"
TARGET_SYSTEM="https://fhir-terminology.ohdsi.org"

curl -s -G "${BASE_URL}/ConceptMap/\$translate" \
  -H "Accept: application/fhir+json" \
  --data-urlencode "system=${SNOMED_SYSTEM}" \
  --data-urlencode "code=${SNOMED_CODE}" \
  --data-urlencode "targetsystem=${TARGET_SYSTEM}" \
  | python3 -m json.tool

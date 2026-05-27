#!/usr/bin/env bash
# Translate SNOMED Hypertensive disorder (38341003) to OMOP concept ID via Echidna ConceptMap/$translate

BASE_URL="https://echidna.fhir.org/r4"
SNOMED_CODE="38341003"
SNOMED_SYSTEM="http://snomed.info/sct"
TARGET_SYSTEM="https://fhir-terminology.ohdsi.org"

curl -s -G "${BASE_URL}/ConceptMap/\$translate" \
  -H "Accept: application/fhir+json" \
  --data-urlencode "system=${SNOMED_SYSTEM}" \
  --data-urlencode "code=${SNOMED_CODE}" \
  --data-urlencode "targetsystem=${TARGET_SYSTEM}" \
  | python3 -m json.tool

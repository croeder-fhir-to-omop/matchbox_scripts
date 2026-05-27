#!/usr/bin/env bash
# Transform a refuted Condition — verificationStatus=refuted should suppress OMOP output

BASE_URL="http://localhost:8080/matchboxv3/fhir"
MAP_URL="http://hl7.org/fhir/uv/omop/StructureMap/ConditionMap"

curl -s -X POST "${BASE_URL}/StructureMap/\$transform?source=${MAP_URL}" \
  -H "Content-Type: application/fhir+json" \
  -H "Accept: application/fhir+json" \
  -d @condition_refuted.json |\
python3 omop_to_csv.py

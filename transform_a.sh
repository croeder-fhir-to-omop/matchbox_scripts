#!/usr/bin/env bash
# Pattern A: inline map via Parameters body
# Both 'resource' and 'map' must be valueString (serialized strings), not embedded resources.
# Python handles all escaping.

PATIENT_FILE="patient.json"
MAP_FILE="PersonMap.fml"
BASE_URL="http://localhost:8080/matchboxv3/fhir"

PARAMS=$(python3 - <<EOF
import json

with open("$PATIENT_FILE") as f:
    patient = json.load(f)

with open("$MAP_FILE") as f:
    map_text = f.read()

params = {
    "resourceType": "Parameters",
    "parameter": [
        {"name": "resource", "valueString": json.dumps(patient, separators=(',', ':'))},
        {"name": "map",      "valueString": map_text}
    ]
}
print(json.dumps(params))
EOF
)

curl -s -X POST "${BASE_URL}/StructureMap/\$transform" \
  -H "Content-Type: application/fhir+json" \
  -H "Accept: application/fhir+json" \
  -d "$PARAMS" | python3 -m json.tool

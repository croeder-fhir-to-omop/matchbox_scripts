#!/usr/bin/env bash
# Pattern A: inline map via Parameters body
# Both 'resource' and 'map' must be valueString (serialized strings), not embedded resources.

PATIENT_FILE="patient.json"
MAP_FILE="PersonMap.fml"
if [ "$1" = "--standalone" ]; then
  BASE_URL="http://localhost:8080/matchboxv3/fhir"
else
  BASE_URL="${MATCHBOX_URL:-http://matchbox:8080}/matchboxv3/fhir"
fi

# Escape a file's contents for embedding as a JSON string value.
# Handles: backslashes, double-quotes, newlines, carriage returns, tabs.
json_escape() {
    local s
    s=$(cat "$1")
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\r'/\\r}"
    s="${s//$'\t'/\\t}"
    printf '%s' "$s"
}

PATIENT_ESC=$(json_escape "$PATIENT_FILE")
MAP_ESC=$(json_escape "$MAP_FILE")

PARAMS="{\"resourceType\":\"Parameters\",\"parameter\":[{\"name\":\"resource\",\"valueString\":\"${PATIENT_ESC}\"},{\"name\":\"map\",\"valueString\":\"${MAP_ESC}\"}]}"

curl -s -X POST "${BASE_URL}/StructureMap/\$transform" \
  -H "Content-Type: application/fhir+json" \
  -H "Accept: application/fhir+json" \
  -d "$PARAMS"

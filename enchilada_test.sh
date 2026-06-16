#!/usr/bin/env bash
# Smoke-test a ConceptMap/$translate terminology server.
#
# Defaults to enchilada running locally via docker-compose (self-signed TLS).
# Override BASE and TLS_FLAG to target another server:
#
#   BASE=https://echidna.fhir.org TLS_FLAG="" bash enchilada_test.sh
#
# NOTE: echidna uses a different Parameters body for $translate — see the
# "echidna format" blocks at the bottom.  The metadata tests are identical.

BASE="${BASE:-https://localhost:8081}"
FHIR="${FHIR:-r4}"
TLS_FLAG="${TLS_FLAG:--k}"   # -k ignores self-signed cert; set TLS_FLAG="" for public CA

pass=0; fail=0

run() {
    local label="$1"; shift
    echo ""
    echo "=== $label ==="
    if out=$(curl -sf $TLS_FLAG "$@" 2>&1); then
        echo "$out" | python3 -m json.tool 2>/dev/null || echo "$out"
        ((pass++))
    else
        echo "FAIL (exit $?)"
        ((fail++))
    fi
}

# ── metadata ────────────────────────────────────────────────────────────────
run "GET $FHIR/metadata" \
    -H "Accept: application/fhir+json" \
    "$BASE/$FHIR/metadata"

run "GET $FHIR/metadata?mode=terminology" \
    -H "Accept: application/fhir+json" \
    "$BASE/$FHIR/metadata?mode=terminology"

# ── translate (enchilada parameter format) ───────────────────────────────────
# These use flat system/code/targetsystem params supported by enchilada.
# For echidna, use the "coding"/"valueCoding" format shown below.

run "POST $FHIR/ConceptMap/\$translate — ICD-10-CM E11.9 (Type 2 diabetes)" \
    -X POST "$BASE/$FHIR/ConceptMap/\$translate" \
    -H "Content-Type: application/fhir+json" \
    -H "Accept: application/fhir+json" \
    -d '{
      "resourceType": "Parameters",
      "parameter": [
        {"name": "system",       "valueUri":  "http://hl7.org/fhir/sid/icd-10-cm"},
        {"name": "code",         "valueCode": "E11.9"},
        {"name": "targetsystem", "valueUri":  "https://athena.ohdsi.org"}
      ]
    }'

run "POST $FHIR/ConceptMap/\$translate — SNOMED 73211009 (Diabetes mellitus)" \
    -X POST "$BASE/$FHIR/ConceptMap/\$translate" \
    -H "Content-Type: application/fhir+json" \
    -H "Accept: application/fhir+json" \
    -d '{
      "resourceType": "Parameters",
      "parameter": [
        {"name": "system",       "valueUri":  "http://snomed.info/sct"},
        {"name": "code",         "valueCode": "73211009"},
        {"name": "targetsystem", "valueUri":  "https://athena.ohdsi.org"}
      ]
    }'

run "POST $FHIR/ConceptMap/\$translate — unknown code (expect result:false)" \
    -X POST "$BASE/$FHIR/ConceptMap/\$translate" \
    -H "Content-Type: application/fhir+json" \
    -H "Accept: application/fhir+json" \
    -d '{
      "resourceType": "Parameters",
      "parameter": [
        {"name": "system",       "valueUri":  "http://snomed.info/sct"},
        {"name": "code",         "valueCode": "DOESNOTEXIST"},
        {"name": "targetsystem", "valueUri":  "https://athena.ohdsi.org"}
      ]
    }'

# ── echidna format (for use with BASE=https://echidna.fhir.org) ──────────────
# Uncomment to test echidna's native parameter format.
#
# run "POST $FHIR/ConceptMap/\$translate — echidna format (SNOMED 73211009)" \
#     -X POST "$BASE/$FHIR/ConceptMap/\$translate" \
#     -H "Content-Type: application/fhir+json" \
#     -H "Accept: application/fhir+json" \
#     -d '{
#       "resourceType": "Parameters",
#       "parameter": [
#         {"name": "coding",       "valueCoding": {"system": "http://snomed.info/sct", "code": "73211009"}},
#         {"name": "targetSystem", "valueUri":    "https://fhir-terminology.ohdsi.org"}
#       ]
#     }'

echo ""
echo "=== Results: $pass passed, $fail failed ==="

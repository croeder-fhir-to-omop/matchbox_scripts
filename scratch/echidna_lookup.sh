#!/usr/bin/env bash
#fails
curl -X GET "https://echidna.fhir.org/r4/CodeSystem/\$lookup?code=resolved" \
  -H "Accept: application/fhir+json"

#{"resourceType":"OperationOutcome","issue":[{"severity":"error","code":"required","details":{"text":"Unable to find a code to lookup (need coding or system/code)"}}]}%           

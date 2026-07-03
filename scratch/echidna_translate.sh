#!/usr/bin/env bash
curl -X POST "https://echidna.fhir.org/r4/ConceptMap/\$translate" \
  -H "Content-Type: application/fhir+json" \
  -H "Accept: application/fhir+json" \
  -d '{
    "resourceType": "Parameters",
    "parameter": [
      {
        "name": "coding",
        "valueCoding": {
          "system": "http://snomed.info/sct",
          "code": "84114007",
          "display": "Heart failure"
        }
      },
      {
        "name": "targetSystem",
        "valueUri": "https://fhir-terminology.ohdsi.org"
      }
    ]
  }'



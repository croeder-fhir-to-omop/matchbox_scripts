#!/usr/bin/env bash

if [ "$1" = "--standalone" ]; then
  BASE_URL="http://localhost:8080/matchboxv3/fhir"
else
  BASE_URL="${MATCHBOX_URL:-http://matchbox:8080}/matchboxv3/fhir"
fi

curl "${BASE_URL}/StructureMap" | grep fullUrl | grep 8080
#echo "================="
#curl http://localhost:8080/matchboxv3/fhir/StructureMap?url=http://hl7.org/fhir/uv/omop/StructureMap/PersonMap 


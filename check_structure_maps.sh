#!/usr/bin/env bash

curl GET http://localhost:8080/matchboxv3/fhir/StructureMap
echo "================="
curl http://localhost:8080/matchboxv3/fhir/StructureMap?url=http://hl7.org/fhir/uv/omop/StructureMap/PersonMap

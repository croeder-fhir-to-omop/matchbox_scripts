# Pattern B: reference map by canonical URL (source query param), body is the resource directly
$BASE_URL = "http://localhost:8080/matchboxv3/fhir"
$MAP_URL  = "http://hl7.org/fhir/uv/omop/StructureMap/PersonMap"

Invoke-RestMethod -Method POST `
    -Uri "$BASE_URL/StructureMap/`$transform?source=$MAP_URL" `
    -ContentType "application/fhir+json" `
    -Headers @{ Accept = "application/fhir+json" } `
    -InFile "patient.json" |
    ConvertTo-Json -Depth 20

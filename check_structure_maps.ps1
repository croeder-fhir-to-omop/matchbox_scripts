$BASE_URL = "http://localhost:8080/matchboxv3/fhir"

Write-Host "=== All StructureMaps ==="
Invoke-RestMethod -Method GET -Uri "$BASE_URL/StructureMap" |
    ConvertTo-Json -Depth 20

Write-Host "================="
Write-Host "=== PersonMap ==="
Invoke-RestMethod -Method GET `
    -Uri "$BASE_URL/StructureMap?url=http://hl7.org/fhir/uv/omop/StructureMap/PersonMap" |
    ConvertTo-Json -Depth 20

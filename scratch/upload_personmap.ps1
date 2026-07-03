# Upload PersonMap.fml to the server so it can be referenced by URL in $transform
$BASE_URL = "http://localhost:8080/matchboxv3/fhir"

Invoke-RestMethod -Method POST `
    -Uri "$BASE_URL/StructureMap" `
    -ContentType "text/fhir-mapping" `
    -Headers @{ Accept = "application/fhir+json" } `
    -InFile "PersonMap.fml" |
    ConvertTo-Json -Depth 20

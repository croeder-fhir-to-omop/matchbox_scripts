$BASE_URL = "http://localhost:8080/matchboxv3/fhir"

Invoke-RestMethod -Method POST `
    -Uri "$BASE_URL/StructureMap/`$transform" `
    -ContentType "application/fhir+json" `
    -InFile "transform.json" |
    ConvertTo-Json -Depth 20

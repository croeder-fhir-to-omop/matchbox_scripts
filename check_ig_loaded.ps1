$BASE_URL = "http://localhost:8080/matchboxv3/fhir"
Invoke-RestMethod -Method GET `
    -Uri "$BASE_URL/ImplementationGuide?_content=omop" `
    -Headers @{ Accept = "application/fhir+json" } |
    ConvertTo-Json -Depth 20

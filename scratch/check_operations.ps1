$BASE_URL = "http://localhost:8080/matchboxv3/fhir"
Invoke-RestMethod -Method GET -Uri "$BASE_URL/metadata" |
    ConvertTo-Json -Depth 20

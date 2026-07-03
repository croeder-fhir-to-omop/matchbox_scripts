# Pattern A: inline map via Parameters body
$BASE_URL     = "http://localhost:8080/matchboxv3/fhir"
$PATIENT_FILE = "patient.json"
$MAP_FILE     = "PersonMap.fml"

$patientJson = Get-Content $PATIENT_FILE -Raw | ConvertFrom-Json | ConvertTo-Json -Compress -Depth 20
$mapText     = Get-Content $MAP_FILE -Raw

$params = @{
    resourceType = "Parameters"
    parameter    = @(
        @{ name = "resource"; valueString = $patientJson },
        @{ name = "map";      valueString = $mapText     }
    )
}

Invoke-RestMethod -Method POST `
    -Uri "$BASE_URL/StructureMap/`$transform" `
    -ContentType "application/fhir+json" `
    -Headers @{ Accept = "application/fhir+json" } `
    -Body ($params | ConvertTo-Json -Depth 10) |
    ConvertTo-Json -Depth 20

# Transform a Condition resource to OMOP ConditionOccurrence via ConditionMap (URL-reference method)
$BASE_URL = "http://localhost:8080/matchboxv3/fhir"
$MAP_URL  = "http://hl7.org/fhir/uv/omop/StructureMap/ConditionMap"

Invoke-RestMethod -Method POST `
    -Uri "$BASE_URL/StructureMap/`$transform?source=$MAP_URL" `
    -ContentType "application/fhir+json" `
    -Headers @{ Accept = "application/fhir+json" } `
    -InFile "condition_hypertension.json" |
    ConvertTo-Json -Depth 20

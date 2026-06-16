# Smoke-test a ConceptMap/$translate terminology server.
#
# Defaults to enchilada running locally via docker-compose (self-signed TLS).
# Override $BASE and $SkipCert to target another server:
#
#   $BASE = "https://echidna.fhir+json"; $SkipCert = $false; .\enchilada_test.ps1
#
# NOTE: echidna uses a different Parameters body for $translate — see the
# "echidna format" blocks at the bottom.  The metadata tests are identical.

param(
    [string]$Base     = "https://localhost:8081",
    [string]$Fhir     = "r4",
    [bool]  $SkipCert = $true   # set $false when targeting a public CA server
)

$pass = 0; $fail = 0

function Run-Test {
    param([string]$Label, [string]$Method = "GET", [string]$Uri, [string]$Body = $null)
    Write-Host "`n=== $Label ===" -ForegroundColor Cyan
    $params = @{
        Method  = $Method
        Uri     = $Uri
        Headers = @{ Accept = "application/fhir+json" }
    }
    if ($SkipCert) {
        # Disable TLS verification for self-signed certs
        if (-not ([System.Management.Automation.PSTypeName]'TrustAllCerts').Type) {
            Add-Type @"
using System.Net; using System.Security.Cryptography.X509Certificates;
public class TrustAllCerts : ICertificatePolicy {
    public bool CheckValidationResult(ServicePoint sp, X509Certificate cert, WebRequest req, int problem) { return true; }
}
"@
        }
        [System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllCerts
    }
    if ($Body) {
        $params.ContentType = "application/fhir+json"
        $params.Body        = $Body
    }
    try {
        $result = Invoke-RestMethod @params
        $result | ConvertTo-Json -Depth 10
        $script:pass++
    } catch {
        Write-Host "FAIL: $_" -ForegroundColor Red
        $script:fail++
    }
}

$translateUri = "$Base/$Fhir/ConceptMap/`$translate"

# ── metadata ────────────────────────────────────────────────────────────────
Run-Test "GET $Fhir/metadata" -Uri "$Base/$Fhir/metadata"
Run-Test "GET $Fhir/metadata?mode=terminology" -Uri "$Base/$Fhir/metadata?mode=terminology"

# ── translate (enchilada parameter format) ───────────────────────────────────
Run-Test "POST $Fhir/ConceptMap/`$translate — ICD-10-CM E11.9 (Type 2 diabetes)" `
    -Method POST -Uri $translateUri -Body '{
  "resourceType": "Parameters",
  "parameter": [
    {"name": "system",       "valueUri":  "http://hl7.org/fhir/sid/icd-10-cm"},
    {"name": "code",         "valueCode": "E11.9"},
    {"name": "targetsystem", "valueUri":  "https://athena.ohdsi.org"}
  ]
}'

Run-Test "POST $Fhir/ConceptMap/`$translate — SNOMED 73211009 (Diabetes mellitus)" `
    -Method POST -Uri $translateUri -Body '{
  "resourceType": "Parameters",
  "parameter": [
    {"name": "system",       "valueUri":  "http://snomed.info/sct"},
    {"name": "code",         "valueCode": "73211009"},
    {"name": "targetsystem", "valueUri":  "https://athena.ohdsi.org"}
  ]
}'

Run-Test "POST $Fhir/ConceptMap/`$translate — unknown code (expect result:false)" `
    -Method POST -Uri $translateUri -Body '{
  "resourceType": "Parameters",
  "parameter": [
    {"name": "system",       "valueUri":  "http://snomed.info/sct"},
    {"name": "code",         "valueCode": "DOESNOTEXIST"},
    {"name": "targetsystem", "valueUri":  "https://athena.ohdsi.org"}
  ]
}'

# ── echidna format (uncomment to test against echidna.fhir.org) ──────────────
# Run-Test "POST $Fhir/ConceptMap/`$translate — echidna format (SNOMED 73211009)" `
#     -Method POST -Uri $translateUri -Body '{
#   "resourceType": "Parameters",
#   "parameter": [
#     {"name": "coding",       "valueCoding": {"system": "http://snomed.info/sct", "code": "73211009"}},
#     {"name": "targetSystem", "valueUri":    "https://fhir-terminology.ohdsi.org"}
#   ]
# }'

Write-Host "`n=== Results: $pass passed, $fail failed ===" -ForegroundColor $(if ($fail -eq 0) { "Green" } else { "Red" })

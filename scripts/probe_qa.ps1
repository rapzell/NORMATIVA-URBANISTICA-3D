param(
  [string]$BaseUrl = 'http://127.0.0.1:8002'
)
$ErrorActionPreference = 'Stop'

function Probe($label, $q){
  Write-Host "=== $label ==="
  $body = @{ pregunta = $q } | ConvertTo-Json -Compress
  try {
    $resp = Invoke-RestMethod -Uri "$BaseUrl/qa" -Method Post -ContentType 'application/json; charset=utf-8' -Body $body
    if ($resp -is [string]) { $resp } else { $resp | ConvertTo-Json -Depth 5 }
  } catch {
    Write-Host $_
  }
  Write-Host ""
}

Probe 'Probe 1: suelo rústico' 'suelo rústico'
Probe 'Probe 2: suelo urbano'  'suelo urbano'
Probe 'Probe 3: A Coruña NR-1: altura y retranqueos' 'A Coruña NR-1: altura y retranqueos'

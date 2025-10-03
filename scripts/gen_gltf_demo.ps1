Param(
  [string]$HostUrl = 'http://127.0.0.1:8002'
)

$ErrorActionPreference = 'Stop'

function Ensure-Backend {
  param([string]$Url)
  Write-Host "[health] Comprobando $Url/health ..."
  try {
    $code = (Invoke-WebRequest -Uri "$Url/health" -UseBasicParsing -TimeoutSec 5).StatusCode
    if ($code -ne 200) { throw "health=$code" }
  } catch {
    throw "Backend no disponible en $Url. Arranca primero con scripts\\open_demo.ps1 -StartServer"
  }
}

function Invoke-Export {
  param(
    [ValidateSet('gltf','glb')][string]$Format,
    [string]$OutFile
  )
  # Construir JSON manualmente para asegurar estructura GeoJSON correcta
  $json = @'
{
  "geometry": {"type":"Polygon","coordinates":[ [[0,0],[10,0],[10,10],[0,10],[0,0]] ]},
  "altura_maxima_m": 5.0,
  "retranqueo_min_m": 0.0,
  "format": "__FMT__"
}
'@
  $json = $json -replace '__FMT__', $Format
  $uri = "$HostUrl/zoning/volume-export?download=true"
  Write-Host "[export] POST $uri format=$Format -> $OutFile"
  Invoke-RestMethod -Uri $uri -Method Post -ContentType 'application/json; charset=utf-8' -Body $json -OutFile $OutFile
}

# Main
Ensure-Backend -Url $HostUrl
$targetDir = Join-Path -Path 'reports' -ChildPath 'exports_gltf'
New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

Invoke-Export -Format 'gltf' -OutFile (Join-Path $targetDir 'demo_square.gltf')
Invoke-Export -Format 'glb'  -OutFile (Join-Path $targetDir 'demo_square.glb')

Write-Host "Listo. Archivos generados en ${targetDir}:"
Get-ChildItem -LiteralPath $targetDir | Select-Object FullName, Length | Format-Table -AutoSize

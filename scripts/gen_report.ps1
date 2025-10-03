param(
  [string]$Municipio = 'Vigo',
  [string]$Subzona = 'RZ-2',
  [double]$Altura = 12,
  [double]$Retanqueo = 3,
  [string]$GeometryPath = 'datos\sample_parcela.geojson',
  [string]$OutPath = 'reports\informe_vigo_rz2.html',
  [string]$Title = 'Informe Vigo RZ-2',
  [string]$Client = 'AC8',
  [string]$Project = 'Vigo QA Local',
  [bool]$Signature = $true,
  [string]$BaseUrl = 'http://127.0.0.1:8002'
)

$ErrorActionPreference = 'Stop'
$outDir = [System.IO.Path]::GetDirectoryName($OutPath)
if (![string]::IsNullOrWhiteSpace($outDir) -and -not (Test-Path $outDir)) {
  New-Item -ItemType Directory -Path $outDir | Out-Null
}

# Leer geometría
$geomJson = Get-Content -Raw -Encoding UTF8 $GeometryPath | ConvertFrom-Json

# Construir payload
$payload = [pscustomobject]@{
  body = [pscustomobject]@{
    geometry = $geomJson
    altura_maxima_m = [double]$Altura
    retranqueo_min_m = [double]$Retanqueo
    municipio = $Municipio
    subzona = $Subzona
    use_plan_front_default = $true
  }
  title = $Title
  client = $Client
  project = $Project
  signature = $Signature
}

$json = $payload | ConvertTo-Json -Depth 50 -Compress

$uri = "$BaseUrl/zoning/assess-report"
Invoke-WebRequest -Uri $uri -Method Post -ContentType 'application/json' -Body $json -OutFile $OutPath

Write-Host "OK:$OutPath"

param(
  [Parameter(Mandatory=$true)] [string]$Municipio,
  [Parameter(Mandatory=$false)] [string]$PdfPath = '',
  [Parameter(Mandatory=$false)] [string]$PagesJsonl = '',
  [Parameter(Mandatory=$false)] [string]$OutAnotJsonl = '',
  [Parameter(Mandatory=$false)] [string]$OutCsv = '',
  [Parameter(Mandatory=$false)] [string]$Manifest = '',
  [Parameter(Mandatory=$false)] [string]$ApiBase = 'http://127.0.0.1:8000',
  [switch]$Apply
)

$ErrorActionPreference = 'Stop'

function Ensure-PathDir([string]$p){
  if (-not [string]::IsNullOrWhiteSpace($p)){
    $d = Split-Path -Parent $p
    if ($d -and -not (Test-Path $d)){
      New-Item -ItemType Directory -Path $d -Force | Out-Null
    }
  }
}

# Rutas por defecto si no se especifican
if (-not $PagesJsonl){ $PagesJsonl = "datos/normativa/$Municipio/texto_paginas.jsonl" }
if (-not $OutAnotJsonl){ $OutAnotJsonl = "datos/anotaciones/${Municipio}_residencial_sugerencias.jsonl" }
if (-not $OutCsv){ $OutCsv = "datos/planes_${Municipio}_residencial.csv" }

Write-Host "[ingesta] Municipio: $Municipio" -ForegroundColor Cyan

# 1) Ingesta PDF → JSONL (si se aportó PdfPath)
if ($PdfPath){
  Ensure-PathDir $PagesJsonl
  $cmd = ".\venv\Scripts\python.exe -u scripts\ingesta_normativa.py --municipio `"$Municipio`" --pdf `"$PdfPath`" --out-jsonl `"$PagesJsonl`""
  if ($Manifest){ $cmd += " --manifest `"$Manifest`"" }
  Write-Host "[ingesta] Ejecutando: $cmd" -ForegroundColor DarkGray
  iex $cmd
} else {
  if (-not (Test-Path $PagesJsonl)){
    throw "No se proporcionó --PdfPath y no existe PagesJsonl: $PagesJsonl"
  }
}

# 2) Extracción heurística → anotaciones JSONL
Ensure-PathDir $OutAnotJsonl
$cmd2 = ".\venv\Scripts\python.exe -u scripts\extract_residencial_from_text.py --municipio `"$Municipio`" --pages-jsonl `"$PagesJsonl`" --out-jsonl `"$OutAnotJsonl`""
Write-Host "[extract] Ejecutando: $cmd2" -ForegroundColor DarkGray
iex $cmd2

# 3) Conversión anotaciones → CSV
Ensure-PathDir $OutCsv
$cmd3 = ".\venv\Scripts\python.exe -u scripts\annotations_to_csv.py --jsonl `"$OutAnotJsonl`" --out `"$OutCsv`""
Write-Host "[convert] Ejecutando: $cmd3" -ForegroundColor DarkGray
iex $cmd3

# 4) Aplicar CSV a la API (opcional)
if ($Apply){
  Write-Host "[apply] Aplicando CSV a $ApiBase/admin/apply-plan-csv-text ..." -ForegroundColor Yellow
  $csvText = [System.IO.File]::ReadAllText($OutCsv, [System.Text.Encoding]::UTF8)
  $body = @{ csv_text = $csvText } | ConvertTo-Json -Compress
  Invoke-RestMethod -Method Post -Uri "$ApiBase/admin/apply-plan-csv-text" -ContentType 'application/json' -Body $body | Out-Null
  Write-Host "[apply] OK" -ForegroundColor Green
}

Write-Host "[done] Ingesta completada." -ForegroundColor Green

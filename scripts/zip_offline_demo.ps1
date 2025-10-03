param(
  [string]$ZipPath = 'reports/demo_offline.zip'
)

$ErrorActionPreference = 'Stop'
$items = @()

# Landing y presets
if (Test-Path 'reports/presentacion.html') { $items += 'reports/presentacion.html' }
$presets = Get-ChildItem -Path 'reports' -Filter 'preset_*.html' -File -ErrorAction SilentlyContinue
if ($presets) { $items += $presets.FullName }

# Informes y paquetes
$informes = Get-ChildItem -Path 'reports' -Filter 'informe_*.html' -File -ErrorAction SilentlyContinue
if ($informes) { $items += $informes.FullName }
if (Test-Path 'reports/informes_demo_full.zip') { $items += 'reports/informes_demo_full.zip' }
if (Test-Path 'reports/exports_cityjson_demo.zip') { $items += 'reports/exports_cityjson_demo.zip' }

# CityJSON
$cityjson = Get-ChildItem -Path 'exports' -Filter '*.city.json' -File -ErrorAction SilentlyContinue
if ($cityjson) { $items += $cityjson.FullName }

if ($items.Count -eq 0) { throw 'No hay contenido para empaquetar' }

$zipDir = [System.IO.Path]::GetDirectoryName($ZipPath)
if (![string]::IsNullOrWhiteSpace($zipDir) -and -not (Test-Path $zipDir)) {
  New-Item -ItemType Directory -Path $zipDir | Out-Null
}
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

Compress-Archive -Path $items -DestinationPath $ZipPath
Write-Host ("OK: " + $ZipPath)

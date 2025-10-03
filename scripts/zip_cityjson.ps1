param(
  [string]$ExportsDir = 'exports',
  [string]$ZipPath = 'reports/exports_cityjson_demo.zip'
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $ExportsDir)) { throw "No existe directorio: $ExportsDir" }
$files = Get-ChildItem -Path $ExportsDir -Filter '*.city.json' -File
if ($files.Count -eq 0) { throw 'No hay CityJSON para empaquetar' }

$zipDir = [System.IO.Path]::GetDirectoryName($ZipPath)
if (![string]::IsNullOrWhiteSpace($zipDir) -and -not (Test-Path $zipDir)) {
  New-Item -ItemType Directory -Path $zipDir | Out-Null
}
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

Compress-Archive -Path $files.FullName -DestinationPath $ZipPath
Write-Host ("OK: " + $ZipPath)

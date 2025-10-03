param(
  [string[]]$Files = @(
    'reports/informe_vigo_rz2.html',
    'reports/informe_acoruna_nr1.html',
    'reports/informe_boiro_ord1.html',
    'reports/informe_boiro_ord3.html'
  ),
  [string]$ZipPath = 'reports/informes_demo.zip'
)

$ErrorActionPreference = 'Stop'

$existing = @()
foreach ($f in $Files) {
  if (Test-Path $f) { $existing += $f }
}
if ($existing.Count -eq 0) { throw 'No hay informes para empaquetar' }

$zipDir = [System.IO.Path]::GetDirectoryName($ZipPath)
if (![string]::IsNullOrWhiteSpace($zipDir) -and -not (Test-Path $zipDir)) {
  New-Item -ItemType Directory -Path $zipDir | Out-Null
}
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

Compress-Archive -Path $existing -DestinationPath $ZipPath
Write-Host ("OK: " + $ZipPath)

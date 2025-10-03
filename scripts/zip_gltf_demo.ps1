$ErrorActionPreference = 'Stop'
$src = Join-Path -Path 'reports' -ChildPath 'exports_gltf'
$zip = Join-Path -Path 'reports' -ChildPath 'exports_gltf_demo.zip'

if (-not (Test-Path -LiteralPath $src)) {
  throw "No existe el directorio de origen: $src"
}
if (Test-Path -LiteralPath $zip) {
  Remove-Item -LiteralPath $zip -Force
}
Compress-Archive -Path (Join-Path $src '*') -DestinationPath $zip -CompressionLevel Optimal
Write-Host "ZIP creado:" (Resolve-Path -LiteralPath $zip)

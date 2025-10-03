param(
  [string]$BaseUrl = 'http://127.0.0.1:8002',
  [int]$HealthTimeoutSec = 20,
  [switch]$StartServer
)

$ErrorActionPreference = 'Stop'

function Test-Health($url, $timeoutSec) {
  try {
    $r = Invoke-WebRequest -Uri "$url/health" -UseBasicParsing -TimeoutSec $timeoutSec
    return $r.StatusCode -eq 200
  } catch { return $false }
}

# Opcional: arrancar backend si no está operativo
if ($StartServer -or -not (Test-Health -url $BaseUrl -timeoutSec $HealthTimeoutSec)) {
  Write-Host 'Iniciando backend (launch_server.cmd)...'
  Start-Process -FilePath 'cmd.exe' -ArgumentList "/c","scripts\launch_server.cmd" -WindowStyle Minimized | Out-Null
  # Esperar a que /health responda
  $deadline = (Get-Date).AddSeconds([Math]::Max($HealthTimeoutSec, 15))
  while ((Get-Date) -lt $deadline) {
    if (Test-Health -url $BaseUrl -timeoutSec 3) { break }
    Start-Sleep -Seconds 1
  }
}

# Construir rutas locales
$repoRoot = Split-Path -Parent $PSScriptRoot
$landing = Join-Path $repoRoot 'reports\presentacion.html'
$viewer = "$BaseUrl/viewer/"

if (-not (Test-Path $landing)) {
  Write-Warning "No se encontró $landing. Asegúrate de haber generado los informes/landing."
}

# Abrir landing y visor en el navegador predeterminado
if (Test-Path $landing) { Start-Process $landing }
Start-Process $viewer

Write-Host "OK: landing y visor abiertos"

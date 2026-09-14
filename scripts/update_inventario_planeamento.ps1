param(
  [string]$Url = "https://abertos.xunta.gal/catalogo/territorio-vivienda-transporte/-/dataset/0032/planeamento-urbanistico-dos-concellos-galicia/001/descarga-directa-ficheiro.csv",
  [string]$OutPath = "datos\inventario_planeamento.csv",
  [switch]$Backup,
  [switch]$VerboseLog
)

$ErrorActionPreference = 'Stop'

function Write-Log($msg){ if($VerboseLog){ Write-Host "[update] $msg" } }

# Asegurar carpeta destino
$destDir = Split-Path -Parent $OutPath
if(-not [string]::IsNullOrWhiteSpace($destDir) -and -not (Test-Path -LiteralPath $destDir)){
  New-Item -ItemType Directory -Force -Path $destDir | Out-Null
}

# Rutas temporales
$tmp = "$OutPath.tmp"
$bak = "$OutPath.bak"

# Descargar a temporal
Write-Log "Descargando: $Url"
Invoke-WebRequest -Uri $Url -OutFile $tmp -UseBasicParsing

# Validación básica
if(-not (Test-Path -LiteralPath $tmp)){
  throw "Descarga fallida: no existe archivo temporal $tmp"
}
$size = (Get-Item -LiteralPath $tmp).Length
if($size -lt 50){
  throw "Archivo descargado demasiado pequeño ($size bytes). Abortando para evitar reemplazo incorrecto."
}

# Si existe anterior, comparar hash para evitar reemplazo innecesario
$needReplace = $true
if(Test-Path -LiteralPath $OutPath){
  try{
    $hNew = (Get-FileHash -Algorithm SHA256 -LiteralPath $tmp).Hash
    $hOld = (Get-FileHash -Algorithm SHA256 -LiteralPath $OutPath).Hash
    if($hNew -eq $hOld){
      Write-Log "El archivo no cambió (hash igual)."
      Remove-Item -LiteralPath $tmp -Force
      $needReplace = $false
    }
  } catch {
    # si falla el hash, seguiremos con reemplazo
    Write-Log "No se pudo calcular hash, se continuará con reemplazo. $_"
  }
}

if($needReplace){
  if($Backup -and (Test-Path -LiteralPath $OutPath)){
    Write-Log "Creando copia de seguridad: $bak"
    Copy-Item -LiteralPath $OutPath -Destination $bak -Force
  }
  Write-Log "Reemplazando $OutPath"
  Move-Item -LiteralPath $tmp -Destination $OutPath -Force
} else {
  Write-Log "Sin cambios."
}

# Metadatos simples: fecha de actualización
try{
  $meta = "# inventario_planeamento.csv actualizado: $(Get-Date -Format o) desde $Url`n"
  $metaPath = Join-Path $destDir "inventario_planeamento.README.txt"
  Set-Content -LiteralPath $metaPath -Value $meta -Encoding UTF8
} catch {}

Write-Host "OK: Inventario actualizado en $OutPath"

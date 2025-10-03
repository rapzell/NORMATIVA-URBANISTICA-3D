param(
  [string]$Municipio,
  [string]$Subzona,
  [ValidateSet('cityjson','gltf','glb')]
  [string]$Format = 'cityjson',
  [string]$GeometryPath = 'datos\sample_parcela.geojson',
  [string]$OutPath = 'exports\modelo.city.json',
  [string]$BaseUrl = 'http://127.0.0.1:8002',
  [double]$Altura = 0,
  [double]$Retanqueo = 0,
  [bool]$UsePlanFrontDefault = $true,
  [ValidateSet('full','min','none')]
  [string]$DiagnosticsVerbosity
)

$ErrorActionPreference = 'Stop'
$dir = [System.IO.Path]::GetDirectoryName($OutPath)
if (![string]::IsNullOrWhiteSpace($dir) -and -not (Test-Path $dir)) {
  New-Item -ItemType Directory -Path $dir | Out-Null
}

$geom = Get-Content -Raw -Encoding UTF8 $GeometryPath | ConvertFrom-Json
# Usar hashtable ordenado para permitir añadir claves opcionales de forma segura
$body = [ordered]@{
  geometry = $geom
  municipio = $Municipio
  subzona = $Subzona
  use_plan_front_default = $UsePlanFrontDefault
  format = $Format
}
if ($Altura -gt 0) { $body['altura_maxima_m'] = [double]$Altura }
if ($Retanqueo -ge 0) { $body['retranqueo_min_m'] = [double]$Retanqueo }

# Reducir diagnósticos por defecto para GLTF para evitar problemas de recursión
if (-not $DiagnosticsVerbosity) {
  if ($Format -eq 'gltf' -or $Format -eq 'glb') { $DiagnosticsVerbosity = 'none' }
}
if ($DiagnosticsVerbosity) { $body['diagnostics_verbosity'] = $DiagnosticsVerbosity }

$json = $body | ConvertTo-Json -Depth 40 -Compress
$uri = "$BaseUrl/zoning/volume-export?download=false"

# Llamada y guardado de salida
$response = Invoke-WebRequest -Uri $uri -Method Post -ContentType 'application/json' -Body $json
if ($Format -eq 'cityjson') {
  # La API devuelve {cityjson:..., diagnostics:...}. Extraer el campo cityjson
  $obj = $response.Content | ConvertFrom-Json
  if ($null -eq $obj.cityjson) {
    Set-Content -Path $OutPath -Value ($response.Content) -Encoding UTF8
  } else {
    $cityjson = ($obj.cityjson | ConvertTo-Json -Depth 100)
    Set-Content -Path $OutPath -Value $cityjson -Encoding UTF8
  }
} else {
  # gltf/glb binario base64? La API suele devolver {gltf: <base64 o json>}
  $obj = $response.Content | ConvertFrom-Json
  if ($Format -eq 'gltf') {
    $gltf = $obj.gltf
    if ($gltf -is [string]) {
      # Si viene como string (JSON), guardar tal cual
      Set-Content -Path $OutPath -Value $gltf -Encoding UTF8
    } else {
      $gltfJson = ($gltf | ConvertTo-Json -Depth 100)
      Set-Content -Path $OutPath -Value $gltfJson -Encoding UTF8
    }
  } elseif ($Format -eq 'glb') {
    # Si la API devuelve un base64 binario (no habitual aquí), decodificar. Si no, guardar JSON completo para referencia.
    if ($null -ne $obj.glb_b64) {
      $bytes = [Convert]::FromBase64String($obj.glb_b64)
      [IO.File]::WriteAllBytes($OutPath, $bytes)
    } else {
      Set-Content -Path $OutPath -Value ($response.Content) -Encoding UTF8
    }
  }
}

Write-Host ("OK: " + $OutPath)

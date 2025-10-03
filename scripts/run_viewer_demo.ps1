Param(
  # Formato de exportación
  [ValidateSet('glb','gltf','cityjson')]
  [string]$Format = 'glb',
  [switch]$Download = $false,
  # Preferencia de librerías para el visor
  [ValidateSet('auto','local','jsdelivr','unpkg')]
  [string]$Lib = 'auto',
  [ValidateRange(0, 2147483647)]
  [int]$TriWarn = 1000000,
  # Parámetros de planeamiento y geometría
  [string]$Municipio,
  [string]$Subzona,
  [ValidateSet('north','east','south','west','')]
  [string]$FrontDirection = '',
  [double]$Altura,
  [double]$Retanqueo,
  [double]$SetbackFront,
  [double]$SetbackSide,
  [double]$SetbackBack,
  [switch]$UsePlanFrontDefault,
  [string]$GeometryPath = '',
  [string]$StreetAxisPath = '',
  [ValidateSet('full','min','none','')]
  [string]$Diagnostics = ''
  , [switch]$Strict
  , [switch]$Gzip
  , [ValidateSet('vigo_centro','vigo_u7','vigo_u10','boiro_rz2','axis_used','axis_ignored','')]
  [string]$Preset = ''
  , [ValidateSet('EPSG:25829','EPSG:4326','WGS84','')]
  [string]$Crs = ''
  , [switch]$Markers
  , [switch]$Echo
  , [string]$SaveBody = ''
  , [switch]$NoOpen
  , [switch]$DiagFull
  , [switch]$Advanced
  , [switch]$PanelsVisible
  , [ValidateSet('top','bottom','bottom-left','')]
  [string]$PanelsPos = ''
  , [switch]$Compact
  , [switch]$Present
  , [int]$Port = 8000
  , [switch]$NoAutoPort
  , [switch]$Smoke
  , [switch]$Fast
  , [string]$LogDir
  , [ValidateRange(1, 3600)] [int]$StartupTimeoutSec = 180
  , [ValidateRange(0, 10)] [int]$RetryCount = 2
  , [ValidateRange(1, 60)] [int]$RetryDelaySec = 2
  , [ValidateSet('fixed','exponential')] [string]$RetryBackoff = 'fixed'
  , [ValidateSet('mock','csv','')]
  [string]$PlanProvider = ''
  , [string]$PlanCSVPath = ''
  , [switch]$Seed
  # Visor: control SIOSE por flags para una demo silenciosa
  , [switch]$NoSiose
  , [switch]$SioseSilent
  # Forzar reinicio de la API si ya hay una instancia en el puerto
  , [switch]$ForceRestart
  # Visor: control SIOTUGA (autodetección WMS) por flags
  , [switch]$NoSiotuga
  , [switch]$SiotugaSilent
  # Modo demo compacto (activa flags silenciosos y arranque rápido)
  , [switch]$Demo
)

# Set working directory to repo root (script relative)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot = Resolve-Path "$ScriptDir\.."
Set-Location $RepoRoot

# Ensure env
$venvPython = Join-Path $RepoRoot 'venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
  # Fallback: usar Python del sistema si no hay venv
  $sysPy = $null
  try { $sysPy = (Get-Command python -ErrorAction SilentlyContinue).Source } catch { $sysPy = $null }

  if ($sysPy) {
    Write-Warning "[warn] No se encontró venv. Usando Python del sistema: $sysPy"
    $venvPython = $sysPy
  } else {
    Write-Error "No se encontró venv ni Python en PATH. Instala dependencias o crea venv."
    Stop-ApiIfSpawned; Stop-TranscriptSafe
    exit 1
  }
}

# Helper: finalizar smoke escribiendo resumen JSON si procede (approved verb)
function Stop-Smoke([int]$ExitCode) {
  try {
    if ($Smoke.IsPresent -and $LogDir) {
      if (-not $script:smokeSummary) { $script:smokeSummary = @{} }
      $script:smokeSummary.end = Get-Date
      if (-not $script:smokeSummary.start) { $script:smokeSummary.start = $script:smokeSummary.end }
      $script:smokeSummary.durationSec = [int]([DateTime]::UtcNow - ($script:smokeSummary.start.ToUniversalTime())).TotalSeconds
      $script:smokeSummary.exitCode = $ExitCode
      try { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null } catch {}
      $outPath = Join-Path $LogDir 'smoke_summary.json'
      $script:smokeSummary | ConvertTo-Json -Depth 6 | Out-File -FilePath $outPath -Encoding UTF8
      Write-Host ("[smoke] Resumen escrito: {0}" -f $outPath) -ForegroundColor DarkGray
    }
  } catch {
    Write-Warning "[smoke] No se pudo escribir smoke_summary.json: $_"
  } finally {
    Stop-ApiIfSpawned; Stop-TranscriptSafe; exit $ExitCode
  }
}

# Start API (uvicorn) if not running; elegir puerto libre si hay conflicto
$env:PYTHONPATH = '.'
$apiProc = $null

function Stop-ApiIfSpawned {
  if ($apiProc) {
    try { Stop-Process -Id $apiProc.Id -Force -ErrorAction SilentlyContinue } catch {}
  }
}

$transcriptStarted = $false
function Stop-TranscriptSafe {
  if ($transcriptStarted) {
    try { Stop-Transcript | Out-Null } catch {}
    $transcriptStarted = $false
  }
}

# Ctrl+C cleanup handler (after functions are defined)
try { Unregister-Event -SourceIdentifier Console_CancelKeyPress -ErrorAction SilentlyContinue } catch {}
$script:cancelHandler = Register-EngineEvent -SourceIdentifier Console_CancelKeyPress -Action {
  try { Write-Warning "Ctrl+C detectado. Limpiando recursos..." } catch {}
  try { Stop-Smoke 5 } catch {
    try { Stop-ApiIfSpawned } catch {}
    try { Stop-TranscriptSafe } catch {}
    [Environment]::Exit(5)
  }
}

function Test-PortOpen {
  param([int]$p)
  try {
    $r = Test-NetConnection -ComputerName 127.0.0.1 -Port $p -WarningAction SilentlyContinue -InformationLevel Quiet
    return [bool]$r
  } catch {
    # Fallback simple: intentar conectar con TcpClient con timeout corto
    try {
      $client = New-Object System.Net.Sockets.TcpClient
      $async = $client.BeginConnect('127.0.0.1', $p, $null, $null)
      $ok = $async.AsyncWaitHandle.WaitOne(150)
      $client.Close()
      return $ok
    } catch { return $false }
  }
}

function Test-ApiUp {
  param([int]$p)
  $u = ("http://127.0.0.1:{0}/openapi.json" -f $p)
  try {
    Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 2 | Out-Null
    return $true
  } catch { return $false }
}

$chosenPort = $Port
$autoPortUsed = $false
$serverRunning = $false

# Si se pide -Demo, activar combinaciones por defecto
if ($Demo.IsPresent) {
  if (-not $Fast.IsPresent) { $Fast = $true }
  if (-not $NoSiose.IsPresent) { $NoSiose = $true }
  if (-not $SioseSilent.IsPresent) { $SioseSilent = $true }
  if (-not $NoSiotuga.IsPresent) { $NoSiotuga = $true }
  if (-not $SiotugaSilent.IsPresent) { $SiotugaSilent = $true }
}
if (Test-ApiUp -p $chosenPort) {
  $serverRunning = $true
} else {
  if (Test-PortOpen -p $chosenPort) {
    if ($NoAutoPort.IsPresent) {
      Write-Error ("El puerto {0} está en uso y -NoAutoPort está activo. Aborta." -f $chosenPort)
      Stop-ApiIfSpawned; Stop-TranscriptSafe; exit 2
    }
    Write-Warning ("El puerto {0} está en uso por otro proceso. Buscando uno libre..." -f $chosenPort)
    $rangeEnd = [math]::Max($chosenPort,8000) + 50
    for ($p = [math]::Max($chosenPort,8000); $p -le $rangeEnd; $p++) {
      if (-not (Test-PortOpen -p $p)) { $chosenPort = $p; break }
    }
    if ($chosenPort -ne $Port) {
      $autoPortUsed = $true
      Write-Host ("Usando puerto alternativo: {0}" -f $chosenPort)
    } else {
      Write-Warning "No se encontró puerto libre cercano; se intentará igualmente el solicitado."
    }
  }
}

# Con el puerto decidido, construir base/pingUrl
$Port = $chosenPort
$base = ("http://127.0.0.1:{0}" -f $Port)
$pingUrl = "$base/openapi.json"

# Pre-configurar provider/CSV en el entorno ANTES de arrancar la API, para que el backend lo lea en startup
try {
  if ($PlanProvider) {
    $env:PLAN_PROVIDER = $PlanProvider
    Write-Host ("[info] (pre) PLAN_PROVIDER={0}" -f $env:PLAN_PROVIDER) -ForegroundColor DarkGray
  }
  if ($PlanCSVPath) {
    try { $resolvedPre = Resolve-Path -LiteralPath $PlanCSVPath -ErrorAction SilentlyContinue } catch { $resolvedPre = $null }
    if ($resolvedPre) { $PlanCSVPath = $resolvedPre.Path }
    $env:PLAN_CSV_PATH = $PlanCSVPath
    Write-Host ("[info] (pre) PLAN_CSV_PATH={0}" -f $env:PLAN_CSV_PATH) -ForegroundColor DarkGray
  }
} catch { Write-Warning ("[plan] Preconfiguración de plan falló: {0}" -f $_) }

# Si hay servidor corriendo y se pide -ForceRestart, terminar proceso en puerto elegido
if ($serverRunning -and $ForceRestart.IsPresent) {
  try {
    Write-Warning ("[force] Forzando reinicio de API en puerto {0}" -f $chosenPort)
    $procId = $null
    try {
      $conn = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $chosenPort -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }
      if (-not $conn) { $conn = Get-NetTCPConnection -LocalPort $chosenPort -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' } }
      if ($conn) { $procId = ($conn | Select-Object -First 1).OwningProcess }
    } catch {}
    if ($procId) {
      try { Stop-Process -Id $procId -Force -ErrorAction Stop; Write-Host ("[force] Proceso {0} detenido" -f $procId) -ForegroundColor DarkYellow } catch { Write-Warning ("[force] No se pudo terminar proceso {0}: {1}" -f $procId, $_) }
    } else {
      Write-Warning "[force] No se encontró proceso escuchando en el puerto; se intentará arrancar igualmente"
    }
  } catch { Write-Warning ("[force] Error al forzar reinicio: {0}" -f $_) }
  $serverRunning = $false
}

if (-not $serverRunning) {
  Write-Host ("Iniciando API en http://localhost:{0} ..." -f $Port)
  if ($Smoke.IsPresent -or $Fast.IsPresent) {
    # Acelera el arranque: no cargar modelos pesados
    $env:API_LOAD_RESOURCES = '0'
    Write-Host "[info] API_LOAD_RESOURCES=0 activado ($(if ($Smoke.IsPresent) { 'Smoke' } else { 'Fast' }))" -ForegroundColor DarkYellow
  }
  $uvicornCmd = ("-m uvicorn app.main:app --host 127.0.0.1 --port {0}" -f $Port)
  if ($LogDir) {
    try {
      New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    } catch {}
    # Registrar también la consola si es posible
    try {
      $tsPath = Join-Path $LogDir 'script_transcript.txt'
      Start-Transcript -Path $tsPath -Append -ErrorAction Stop | Out-Null
      $transcriptStarted = $true
      Write-Host ("[info] Transcript de consola en: {0}" -f $tsPath) -ForegroundColor DarkGray
    } catch {
      Write-Warning "[warn] No se pudo iniciar transcript de consola: $_"
    }
    $stdoutPath = Join-Path $LogDir 'uvicorn_stdout.txt'
    $stderrPath = Join-Path $LogDir 'uvicorn_stderr.txt'
    Write-Host ("[info] Redirigiendo logs a {0} y {1}" -f $stdoutPath, $stderrPath) -ForegroundColor DarkGray
    $apiProc = Start-Process -PassThru -NoNewWindow -FilePath $venvPython -ArgumentList $uvicornCmd -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
  } else {
    $apiProc = Start-Process -PassThru -NoNewWindow -FilePath $venvPython -ArgumentList $uvicornCmd
  }
  # Espera hasta que responda /health (controlado por -StartupTimeoutSec)
  $deadline = (Get-Date).AddSeconds($StartupTimeoutSec)
  Write-Host -NoNewline 'Esperando a que la API inicie'
  do {
    Start-Sleep -Milliseconds 500
    Write-Host -NoNewline '.'
    try {
      Invoke-WebRequest -Uri $pingUrl -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop | Out-Null
      $serverRunning = $true
    } catch {
      $serverRunning = $false
    }
  } while((-not $serverRunning) -and (Get-Date) -lt $deadline)
  Write-Host ''
}

if (-not $serverRunning) {
  Write-Warning 'La API aún no respondió. Puede estar descargando modelos. Abriré el visor igualmente; refresca cuando el backend esté listo.'
}

# Si se proporcionan proveedor y/o CSV de plan, configurarlos y validarlos
try {
  if ($PlanProvider) {
    $env:PLAN_PROVIDER = $PlanProvider
    Write-Host ("[info] PLAN_PROVIDER={0}" -f $env:PLAN_PROVIDER) -ForegroundColor DarkGray
  }
  if ($PlanCSVPath) {
    try {
      $resolved = Resolve-Path -LiteralPath $PlanCSVPath -ErrorAction SilentlyContinue
    } catch { $resolved = $null }
    if ($resolved) { $PlanCSVPath = $resolved.Path }
    $env:PLAN_CSV_PATH = $PlanCSVPath
    Write-Host ("[info] PLAN_CSV_PATH={0}" -f $env:PLAN_CSV_PATH) -ForegroundColor DarkGray
    # Validar CSV vía API
    try {
      $valUrl = "$base/zoning/validate-plan-csv"
      $payload = @{ path = $env:PLAN_CSV_PATH } | ConvertTo-Json -Compress
      $resp = Invoke-WebRequest -Uri $valUrl -UseBasicParsing -TimeoutSec 10 -Method POST -Body $payload -ContentType 'application/json; charset=UTF-8'
      $obj = $null
      try { $obj = $resp.Content | ConvertFrom-Json } catch {}
      if ($obj) {
        if ($obj.valid -eq $true) {
          Write-Host ("[plan] CSV válido (errors={0}, warnings={1})" -f $obj.summary.errors, $obj.summary.warnings) -ForegroundColor Green
        } else {
          Write-Warning ("[plan] CSV con errores (errors={0}, warnings={1})" -f $obj.summary.errors, $obj.summary.warnings)
        }
      } else { Write-Warning "[plan] No se pudo parsear respuesta de validación" }
    } catch { Write-Warning ("[plan] Validación CSV falló: {0}" -f $_) }
    # Recargar plan si provider=csv
    if (($env:PLAN_PROVIDER -eq 'csv') -and $env:PLAN_CSV_PATH) {
      try {
        $relUrl = "$base/admin/reload-plan"
        $payload2 = @{ path = $env:PLAN_CSV_PATH } | ConvertTo-Json -Compress
        $resp2 = Invoke-WebRequest -Uri $relUrl -UseBasicParsing -TimeoutSec 15 -Method POST -Body $payload2 -ContentType 'application/json; charset=UTF-8'
        Write-Host ("[plan] Recarga aplicada: {0}" -f $resp2.Content)
      } catch { Write-Warning ("[plan] Recarga CSV falló: {0}" -f $_) }
    }
  }
} catch { Write-Warning ("[plan] Configuración de plan falló: {0}" -f $_) }

# Construir cuerpo JSON para /zoning/volume-export
$fmt = $Format.ToLower()
if ($fmt -notin @('glb','gltf','cityjson')) { $fmt = 'glb' }

# Presets: establecen valores por defecto si no están dados explícitamente
if ($Preset) {
  switch ($Preset) {
    'vigo_centro' {
      if (-not $Municipio) { $Municipio = 'Vigo' }
      if (-not $UsePlanFrontDefault.IsPresent -and -not $FrontDirection) { $UsePlanFrontDefault = $true }
      if (-not $GeometryPath) { $GeometryPath = 'datos\sample_parcela.geojson' }
    }
    'vigo_u7' {
      if (-not $Municipio) { $Municipio = 'Vigo' }
      if (-not $Subzona)   { $Subzona   = 'U7' }
      if (-not $UsePlanFrontDefault.IsPresent -and -not $FrontDirection) { $UsePlanFrontDefault = $true }
      if (-not $GeometryPath) { $GeometryPath = 'datos\sample_parcela.geojson' }
    }
    'vigo_u10' {
      if (-not $Municipio) { $Municipio = 'Vigo' }
      if (-not $Subzona)   { $Subzona   = 'U10' }
      if (-not $UsePlanFrontDefault.IsPresent -and -not $FrontDirection) { $UsePlanFrontDefault = $true }
      if (-not $GeometryPath) { $GeometryPath = 'datos\sample_parcela.geojson' }
    }
    'boiro_rz2' {
      if (-not $Municipio) { $Municipio = 'Boiro' }
      if (-not $Subzona)   { $Subzona   = 'RZ-2' }
      if (-not $FrontDirection) { $FrontDirection = 'north' }
      if (-not $GeometryPath) { $GeometryPath = 'datos\sample_parcela.geojson' }
    }
    'axis_used' {
      # 10x10 parcel at origin; street axis along south edge (y = 0)
      $geometry = '{"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]}' | ConvertFrom-Json
      $streetAxis = '{"type":"LineString","coordinates":[[0,-1],[10,-1]]}' | ConvertFrom-Json
      if (-not $Crs) { $Crs = 'EPSG:25829' }
      # Aportar altura por defecto si no se indicó explícitamente, para evitar 400 (faltan parámetros)
      if (-not $PSBoundParameters.ContainsKey('Altura')) { $Altura = 8 }
      if (-not $PSBoundParameters.ContainsKey('Diagnostics') -and -not $Diagnostics) { $Diagnostics = 'full' }
    }
    'axis_ignored' {
      # Same parcel; street axis far away to trigger ignore (e.g., y = -200)
      $geometry = '{"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]}' | ConvertFrom-Json
      $streetAxis = '{"type":"LineString","coordinates":[[0,-200],[10,-200]]}' | ConvertFrom-Json
      if (-not $Crs) { $Crs = 'EPSG:25829' }
      # Aportar altura por defecto si no se indicó explícitamente, para evitar 400 (faltan parámetros)
      if (-not $PSBoundParameters.ContainsKey('Altura')) { $Altura = 8 }
      if (-not $PSBoundParameters.ContainsKey('Diagnostics') -and -not $Diagnostics) { $Diagnostics = 'full' }
    }
  }
}

# Defaults de seguridad de Altura
# Evitar forzar Altura cuando se proporcionan Municipio/Subzona (queremos que la API derive del plan)
if (-not $PSBoundParameters.ContainsKey('Altura')) {
  if (-not $Municipio -and -not $Subzona) {
    $Altura = 8
  } else {
    # No establecer Altura por defecto para no sobreescribir parámetros del plan
    # Dejar $Altura en 0 (no se incluirá en el body si no fue pasado explícitamente)
    $Altura = 0
  }
} elseif ($Altura -le 0) {
  Write-Warning "Altura (m) debe ser > 0. Se recibió $Altura; usando 8 m por defecto."
  $Altura = 8
}
# Si el usuario no aportó preset ni rutas de geometría/eje, usar por defecto la geometría de ejemplo en Galicia
if (-not $Preset -and -not $GeometryPath -and -not $StreetAxisPath) {
  $GeometryPath = 'datos\sample_parcela.geojson'
  if (-not $Municipio) { $Municipio = 'Vigo' }
}
if (-not $Municipio -and -not $Subzona) { $Municipio = 'Vigo' }
if (-not $UsePlanFrontDefault.IsPresent -and -not $FrontDirection) { $UsePlanFrontDefault = $true }

# Geometría: cargar desde fichero si se aporta, si no usar cuadrado de ejemplo (vía JSON para preservar anidado)
if ($GeometryPath -and (Test-Path $GeometryPath)) {
  try {
    $gjson = Get-Content -Raw -Path $GeometryPath | ConvertFrom-Json
    # Acepta Geometry | Feature | FeatureCollection
    $gtype = ($gjson.type | ForEach-Object { $_.ToString() })
    if ($gtype -eq 'Feature') {
      $geometry = $gjson.geometry
      Write-Host "[info] GeometryPath contiene Feature: extraída 'geometry'"
    } elseif ($gtype -eq 'FeatureCollection') {
      if ($gjson.features -and $gjson.features.Count -ge 1) {
        $geometry = $gjson.features[0].geometry
        Write-Host "[info] GeometryPath contiene FeatureCollection: usada geometry del primer feature"
      }
    } else {
      $geometry = $gjson
    }
  } catch {}
}
if (-not $geometry) {
  $geometry = '{"type":"Polygon","coordinates":[[[0,0],[2,0],[2,2],[0,2],[0,0]]]}' | ConvertFrom-Json
}

# Auto-detect CRS if not provided: WGS84 if coords within lon/lat ranges, else EPSG:25829 (Galicia)
if (-not $Crs) {
  try {
    $first = $null
    $gt = ($geometry.type | ForEach-Object { $_.ToString() })
    if ($gt -eq 'Polygon') {
      $first = $geometry.coordinates[0][0]
    } elseif ($gt -eq 'MultiPolygon') {
      $first = $geometry.coordinates[0][0][0]
    } elseif ($gt -eq 'LineString') {
      $first = $geometry.coordinates[0]
    } elseif ($gt -eq 'MultiLineString') {
      $first = $geometry.coordinates[0][0]
    } elseif ($gt -eq 'Point') {
      $first = $geometry.coordinates
    }
    if ($first -and $first.Count -ge 2) {
      $x = [double]$first[0]; $y = [double]$first[1]
      if ([double]::IsFinite($x) -and [double]::IsFinite($y)) {
        if ([math]::Abs($x) -le 180 -and [math]::Abs($y) -le 90) {
          $Crs = 'EPSG:4326'
        } else {
          $Crs = 'EPSG:25829'
        }
        Write-Host "[info] CRS autodetect: $Crs"
      }
    }
  } catch { }
}

# Eje de calle opcional
if ($StreetAxisPath -and (Test-Path $StreetAxisPath)) {
  try {
    $sjson = Get-Content -Raw -Path $StreetAxisPath | ConvertFrom-Json
    $stype = ($sjson.type | ForEach-Object { $_.ToString() })
    if ($stype -eq 'Feature') {
      $streetAxis = $sjson.geometry
      Write-Host "[info] StreetAxisPath contiene Feature: extraída 'geometry'"
    } elseif ($stype -eq 'FeatureCollection') {
      if ($sjson.features -and $sjson.features.Count -ge 1) {
        $streetAxis = $sjson.features[0].geometry
        Write-Host "[info] StreetAxisPath contiene FeatureCollection: usada geometry del primer feature"
      }
    } else {
      $streetAxis = $sjson
    }
  } catch {}
}

$geomType = ($geometry.type | ForEach-Object { $_.ToString() })
$hasHoles = $false
try {
  if ($geomType -eq 'Polygon') {
    if ($geometry.coordinates -and $geometry.coordinates.Count -gt 1) { $hasHoles = $true }
  }
} catch {}
if ($fmt -in @('glb','gltf')) {
  if ($geomType -eq 'MultiPolygon' -or $hasHoles) {
    Write-Warning "La exportación $fmt no soporta MultiPolygon ni Polygon con huecos; considera usar -Format cityjson"
  }
}

$body = [ordered]@{ geometry = $geometry }
# Incluir Altura si fue pasada como parámetro explícito o si es > 0 (evitar enviar 0 por defecto que sobreescriba el plan)
if ($PSBoundParameters.ContainsKey('Altura') -or ([double]$Altura -gt 0))  { $body.altura_maxima_m   = [double]$Altura }
if ($PSBoundParameters.ContainsKey('Retanqueo'))   { $body.retranqueo_min_m  = [double]$Retanqueo }
if ($PSBoundParameters.ContainsKey('SetbackFront')){ $body.setback_front_m   = [double]$SetbackFront }
if ($PSBoundParameters.ContainsKey('SetbackSide')) { $body.setback_side_m    = [double]$SetbackSide }
if ($PSBoundParameters.ContainsKey('SetbackBack')) { $body.setback_back_m    = [double]$SetbackBack }
if ($Municipio)                                     { $body.municipio         = $Municipio }
if ($Subzona)                                       { $body.subzona           = $Subzona }
if ($FrontDirection)                                { $body.front_direction   = $FrontDirection }
if ($UsePlanFrontDefault.IsPresent)                 { $body.use_plan_front_default = $true }
if ($streetAxis)                                    { $body.street_axis       = $streetAxis }
if ($Diagnostics)                                   { $body.diagnostics_verbosity = $Diagnostics }
if ($Crs)                                           { $body.crs               = $Crs }

# Convertir a JSON y base64 url-safe
$jsonBody = ($body | ConvertTo-Json -Depth 20 -Compress)
$bytes = [System.Text.Encoding]::UTF8.GetBytes($jsonBody)
$b64 = [Convert]::ToBase64String($bytes).Replace('+','-').Replace('/','_')

if ($Echo.IsPresent) {
  Write-Host "[debug] JSON body:" -ForegroundColor Cyan
  Write-Host $jsonBody
}

# Guardar cuerpo JSON si se solicita
if ($SaveBody) {
  try {
    $outPath = Resolve-Path -LiteralPath $SaveBody -ErrorAction SilentlyContinue
  } catch { $outPath = $null }
  if (-not $outPath) { $outPath = $SaveBody }
  try {
    $dir = Split-Path -Parent $outPath
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    Set-Content -LiteralPath $outPath -Value ($body | ConvertTo-Json -Depth 20) -Encoding UTF8
    Write-Host "[info] JSON guardado en: $outPath"
  } catch {
    Write-Warning "[warn] No se pudo guardar JSON en: $SaveBody ($_ )"
  }
}

# Construir URL del export con body embebido para que el visor haga POST con ese cuerpo
$exportUrl = "$base/zoning/volume-export?format=$fmt"
if ($Download -and $fmt -in @('glb','gltf','cityjson')) { $exportUrl += '&download=true' }
if ($Strict.IsPresent) { $exportUrl += '&strict=true' }
if ($fmt -eq 'cityjson' -and $Gzip.IsPresent) { $exportUrl += '&gzip=true' }
$exportUrl += "&body_b64=$b64"

if ($Echo.IsPresent) {
  Write-Host "[debug] Export URL:" -ForegroundColor Cyan
  Write-Host $exportUrl
}

# Open viewer served by FastAPI to avoid CORS and file path issues
$viewerHttp = "$base/viewer/"
# Pass lib selection first so the viewer sets preference before dependency load
$viewerWithQuery = "$viewerHttp`?lib=$Lib&triWarn=$TriWarn&url=$([System.Uri]::EscapeDataString($exportUrl))"
# If DEM provider keys are available in env, pass them through so the viewer picks them up without UI
try {
  if ($env:MAPTILER_KEY) {
    $viewerWithQuery += ('&maptilerKey=' + [System.Uri]::EscapeDataString($env:MAPTILER_KEY))
  }
  if ($env:NEXTZEN_KEY) {
    $viewerWithQuery += ('&nextzenKey=' + [System.Uri]::EscapeDataString($env:NEXTZEN_KEY))
  }
} catch {}
if ($autoPortUsed) { $viewerWithQuery += '&autop=1' }
if ($DiagFull.IsPresent) { $viewerWithQuery += '&diag=full' }
if ($Markers.IsPresent) { $viewerWithQuery += '&markers=1' }
if ($Advanced.IsPresent) { $viewerWithQuery += '&adv=1' }
if ($PanelsVisible.IsPresent) { $viewerWithQuery += '&panels=1' }
if ($PanelsPos) { $viewerWithQuery += ('&panpos=' + $PanelsPos) }
if ($Compact.IsPresent) { $viewerWithQuery += '&compact=1' }
if ($Present.IsPresent) { $viewerWithQuery += '&present=1' }
if ($Seed.IsPresent) { $viewerWithQuery += '&seed=1' }
# Inyectar flags de SIOSE si se solicitan; -Fast implica silencioso por defecto
if ($NoSiose.IsPresent) { $viewerWithQuery += '&siose=0' }
if ($SioseSilent.IsPresent -or $Fast.IsPresent) { $viewerWithQuery += '&siose_silent=1' }
# Inyectar flags de SIOTUGA (autodetección WMS) si se solicitan
if ($NoSiotuga.IsPresent) { $viewerWithQuery += '&siotuga=0' }
if ($SiotugaSilent.IsPresent -or $Fast.IsPresent) { $viewerWithQuery += '&siotuga_silent=1' }

if ($Smoke.IsPresent) {
  $script:smokeSummary = @{
    start = Get-Date
    retry = @{ count = [int]$RetryCount; delaySec = [int]$RetryDelaySec; backoff = "$RetryBackoff" }
    getViewer = @{}
    postExport = @{}
  }
  Write-Host ("[smoke] Retry policy: count={0}, delay={1}s, backoff={2}" -f $RetryCount, $RetryDelaySec, $RetryBackoff) -ForegroundColor DarkCyan
  Write-Host "[smoke] Probando /viewer/ ..." -ForegroundColor Yellow
  try {
  $maxRetriesViewer = [int]$RetryCount
  for ($attemptV = 0; $attemptV -le $maxRetriesViewer; $attemptV++) {
    $isLastV = ($attemptV -eq $maxRetriesViewer)
    try {
      $resp1 = Invoke-WebRequest -Uri $viewerHttp -UseBasicParsing -TimeoutSec 10 -Method GET
      if ($resp1.StatusCode -ge 200 -and $resp1.StatusCode -lt 300) {
        Write-Host "[smoke] /viewer/ OK ($($resp1.StatusCode))" -ForegroundColor Green
        $script:smokeSummary.getViewer = @{ attempts = $attemptV + 1; lastStatus = [int]$resp1.StatusCode; success = $true }
        break
      } else {
        if (-not $isLastV) {
          Write-Warning "[smoke] /viewer/ fallo ($($resp1.StatusCode)). Reintentando (intento $($attemptV+2)/$($maxRetriesViewer+1))..."
          $delayV = [int]$RetryDelaySec
          if ($RetryBackoff -eq 'exponential') { $delayV = [int][math]::Ceiling($RetryDelaySec * [math]::Pow(2, $attemptV)) }
          Write-Host ("[smoke] Esperando {0}s antes de reintentar..." -f $delayV) -ForegroundColor DarkGray
          Start-Sleep -Seconds $delayV
          continue
        } else {
          $script:smokeSummary.getViewer = @{ attempts = $attemptV + 1; lastStatus = [int]$resp1.StatusCode; success = $false }
          Write-Error "[smoke] /viewer/ fallo ($($resp1.StatusCode))"; Stop-Smoke 3
        }
      }
    } catch {
      if (-not $isLastV) {
        Write-Warning "[smoke] /viewer/ error transitorio: $_. Reintentando (intento $($attemptV+2)/$($maxRetriesViewer+1))..."
        $delayV = [int]$RetryDelaySec
        if ($RetryBackoff -eq 'exponential') { $delayV = [int][math]::Ceiling($RetryDelaySec * [math]::Pow(2, $attemptV)) }
        Write-Host ("[smoke] Esperando {0}s antes de reintentar..." -f $delayV) -ForegroundColor DarkGray
        Start-Sleep -Seconds $delayV
        continue
      } else {
        $script:smokeSummary.getViewer = @{ attempts = $attemptV + 1; lastStatus = $null; error = ("{0}" -f $_); success = $false }
        Write-Error "[smoke] /viewer/ error: $_"; Stop-Smoke 3
      }
    }
  }

  Write-Host "[smoke] Probando POST /zoning/volume-export ..." -ForegroundColor Yellow
  $postUrl = "$base/zoning/volume-export?format=$fmt"
  if ($Strict.IsPresent) { $postUrl += '&strict=true' }
  if ($fmt -eq 'cityjson' -and $Gzip.IsPresent) { $postUrl += '&gzip=true' }
  $maxRetries = [int]$RetryCount
  for ($attempt = 0; $attempt -le $maxRetries; $attempt++) {
    $isLast = ($attempt -eq $maxRetries)
    try {
      $resp2 = Invoke-WebRequest -Uri $postUrl -UseBasicParsing -TimeoutSec 60 -Method POST -Body $jsonBody -ContentType 'application/json; charset=UTF-8'
      if ($resp2.StatusCode -ge 200 -and $resp2.StatusCode -lt 300) {
        Write-Host "[smoke] POST export OK ($($resp2.StatusCode))" -ForegroundColor Green
        $script:smokeSummary.postExport = @{ attempts = $attempt + 1; lastStatus = [int]$resp2.StatusCode; success = $true }
        Stop-Smoke 0
      }
      $code = [int]$resp2.StatusCode
      if ($code -ge 500 -and -not $isLast) {
        Write-Warning "[smoke] POST fallo $code. Reintentando (intento $($attempt+2)/$($maxRetries+1))..."
        $delay = [int]$RetryDelaySec
        if ($RetryBackoff -eq 'exponential') { $delay = [int][math]::Ceiling($RetryDelaySec * [math]::Pow(2, $attempt)) }
        Write-Host ("[smoke] Esperando {0}s antes de reintentar..." -f $delay) -ForegroundColor DarkGray
        Start-Sleep -Seconds $delay
        continue
      } else {
        $script:smokeSummary.postExport = @{ attempts = $attempt + 1; lastStatus = $code; success = $false }
        Write-Error "[smoke] POST export fallo ($code)"; Stop-Smoke 4
      }
    } catch {
      if (-not $isLast) {
        Write-Warning "[smoke] POST error transitorio: $_. Reintentando (intento $($attempt+2)/$($maxRetries+1))..."
        $delay = [int]$RetryDelaySec
        if ($RetryBackoff -eq 'exponential') { $delay = [int][math]::Ceiling($RetryDelaySec * [math]::Pow(2, $attempt)) }
        Write-Host ("[smoke] Esperando {0}s antes de reintentar..." -f $delay) -ForegroundColor DarkGray
        Start-Sleep -Seconds $delay
        continue
      } else {
        $script:smokeSummary.postExport = @{ attempts = $attempt + 1; lastStatus = $null; error = ("{0}" -f $_); success = $false }
        Write-Error "[smoke] POST export error: $_"; Stop-Smoke 4
      }
    }
  }
  } catch {
    $script:smokeSummary.unhandledError = ("{0}" -f $_)
    Write-Error "[smoke] Excepción no controlada: $_"
    Stop-Smoke 4
  }
}

Write-Host ("Abriendo visor: {0}" -f $viewerWithQuery)
if ($NoOpen.IsPresent -or $Smoke.IsPresent) {
  Write-Host "[info] NoOpen activo: abre manualmente la URL anterior si deseas continuar"
} else {
  # Try to open in default browser; if it fails, print URL for manual open
  try {
    Start-Process "$viewerWithQuery"
  } catch {
    Write-Warning "No se pudo abrir el navegador automáticamente. Abre esta URL manualmente:"
    Write-Host $viewerWithQuery
  }
}

# Si hay transcript, cerrarlo al final en ejecuciones interactivas
Stop-TranscriptSafe

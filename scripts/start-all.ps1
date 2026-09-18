# EA Bot - start semua service (Python API, Node API, Web Dashboard).
# Pakai: start.bat  (atau: npm run up). Flag: -NoBrowser
param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Info($m) { Write-Host $m }
function Ok($m)   { Write-Host $m -ForegroundColor Green }
function Warn($m) { Write-Host $m -ForegroundColor Yellow }
function Fail($m) { Write-Host $m -ForegroundColor Red }

Info "=== EA Bot - start semua service ==="
Info "Root: $root"

# -- 0. Muat .env.runtime (rahasia lokal; gitignored) ----------------------
$envMap = @{}
$runtimeFile = Join-Path $root '.env.runtime'
if (Test-Path $runtimeFile) {
  Get-Content $runtimeFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith('#')) { return }
    $i = $line.IndexOf('=')
    if ($i -lt 1) { return }
    $envMap[$line.Substring(0, $i).Trim()] = $line.Substring($i + 1).Trim()
  }
  Info "[env] .env.runtime dimuat ($($envMap.Count) entri)"
} else {
  Warn "[env] .env.runtime belum ada - memakai default"
}

function EnvOr([string]$key, [string]$fallback) {
  if ($envMap.ContainsKey($key) -and $envMap[$key]) { return $envMap[$key] }
  return $fallback
}

$jwt      = EnvOr 'JWT_SECRET' ''
$devAuth  = EnvOr 'DEV_AUTH_ENABLED' 'true'
$nodePort = EnvOr 'PORT' '3001'
$pyUrl    = EnvOr 'PYTHON_SERVICE_URL' 'http://127.0.0.1:8000'
$mt5Live  = EnvOr 'MT5_LIVE_DATA' 'true'
$nineUrl  = EnvOr 'NINE_ROUTER_BASE_URL' 'http://127.0.0.1:20128/v1'
$nineKey  = EnvOr 'NINE_ROUTER_API_KEY' ''
$tgToken  = EnvOr 'TELEGRAM_BOT_TOKEN' ''
$tgChats  = EnvOr 'TELEGRAM_ALLOWED_CHAT_IDS' ''
$feedOn   = EnvOr 'MARKET_FEED_ENABLED' 'false'
$feedSyms = EnvOr 'MARKET_FEED_SYMBOLS' 'XAUUSD'
$feedTf   = EnvOr 'MARKET_FEED_TIMEFRAME' 'M5'
$feedInt  = EnvOr 'MARKET_FEED_INTERVAL_S' '60'
$lessonP  = EnvOr 'LESSON_STORE_PATH' ''

if (-not $jwt) {
  $bytes = New-Object byte[] 24
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $jwt = [Convert]::ToBase64String($bytes)
  Add-Content -Path $runtimeFile -Value "JWT_SECRET=$jwt"
  Warn "[env] JWT_SECRET baru dibuat & disimpan ke .env.runtime"
}

function Test-Port([int]$port) {
  $hit = netstat -ano | Select-String -Pattern 'LISTENING' | Select-String -Pattern ":$port\s"
  return [bool]$hit
}

function Wait-Health([string]$url, [int]$timeoutSec = 60) {
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
      if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { return $true }
    } catch { Start-Sleep -Milliseconds 800 }
  }
  return $false
}

$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$mt5 = Get-Process -Name 'terminal64' -ErrorAction SilentlyContinue
if ($mt5) { Info "[mt5] terminal terdeteksi: $($mt5.Count) proses" }
else { Warn "[mt5] terminal tidak terdeteksi - Python jalan tanpa data live" }

# -- 1. Python API :8000 ----------------------------------------------------
Info ""
Info "[1/3] Python API :8000"
if (Test-Port 8000) {
  Ok "      sudah berjalan - dilewati"
} else {
  $pyDir = Join-Path $root 'services\python'
  $pyExe = Join-Path $pyDir '.venv\Scripts\python.exe'
  if (-not (Test-Path $pyExe)) { Fail "      venv tidak ditemukan: $pyExe"; exit 1 }
  $env:MT5_LIVE_DATA = $mt5Live
  $env:NINE_ROUTER_BASE_URL = $nineUrl
  if ($nineKey) { $env:NINE_ROUTER_API_KEY = $nineKey }
  if ($tgToken) { $env:TELEGRAM_BOT_TOKEN = $tgToken }
  if ($tgChats) { $env:TELEGRAM_ALLOWED_CHAT_IDS = $tgChats }
  # Market feed loop (Fase 6) — OFF unless the operator opts in.
  $env:MARKET_FEED_ENABLED = $feedOn
  $env:MARKET_FEED_SYMBOLS = $feedSyms
  $env:MARKET_FEED_TIMEFRAME = $feedTf
  $env:MARKET_FEED_INTERVAL_S = $feedInt
  # Lesson store (Fase 7) — persistent JSONL path (default logs/lessons.jsonl).
  if ($lessonP) { $env:LESSON_STORE_PATH = $lessonP }
  Start-Process -FilePath $pyExe `
    -ArgumentList '-m', 'uvicorn', 'src.main:app', '--host', '127.0.0.1', '--port', '8000' `
    -WorkingDirectory $pyDir -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDir 'python.log') `
    -RedirectStandardError (Join-Path $logDir 'python.err.log')
  if (Wait-Health 'http://127.0.0.1:8000/health' 45) { Ok "      mulai - sehat" }
  else { Fail "      GAGAL sehat - cek logs\python.err.log" }
}

# -- 2. Node API :3001 ------------------------------------------------------
Info ""
Info "[2/3] Node API :$nodePort"
if (Test-Port ([int]$nodePort)) {
  Ok "      sudah berjalan - dilewati"
} else {
  $apiDir = Join-Path $root 'apps\api'
  if (-not (Test-Path (Join-Path $apiDir 'dist\index.js'))) {
    Warn "      dist belum ada - build (npm run build)..."
    Push-Location $apiDir; npm run build; Pop-Location
  }
  $env:JWT_SECRET = $jwt
  $env:DEV_AUTH_ENABLED = $devAuth
  $env:PORT = $nodePort
  $env:PYTHON_SERVICE_URL = $pyUrl
  Start-Process -FilePath 'node' -ArgumentList 'dist/index.js' `
    -WorkingDirectory $apiDir -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDir 'node.log') `
    -RedirectStandardError (Join-Path $logDir 'node.err.log')
  if (Wait-Health "http://127.0.0.1:$nodePort/health" 30) { Ok "      mulai - sehat" }
  else { Fail "      GAGAL sehat - cek logs\node.err.log" }
}

# -- 3. Web Dashboard :3200 -------------------------------------------------
Info ""
Info "[3/3] Web Dashboard :3200"
if (Test-Port 3200) {
  Ok "      sudah berjalan - dilewati"
} else {
  $webDir = Join-Path $root 'apps\web'
  if (-not (Test-Path (Join-Path $webDir '.next\BUILD_ID'))) {
    Warn "      build web belum ada - build (1-2 menit)..."
    Push-Location $webDir; npm run build; Pop-Location
  }
  Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'npm run start -- -p 3200' `
    -WorkingDirectory $webDir -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDir 'web.log') `
    -RedirectStandardError (Join-Path $logDir 'web.err.log')
  if (Wait-Health 'http://127.0.0.1:3200/' 60) { Ok "      mulai - sehat" }
  else { Fail "      GAGAL sehat - cek logs\web.err.log" }
}

# -- 4. Ringkasan -----------------------------------------------------------
Info ""
Info "=== Ringkasan ==="
$pyOk  = Wait-Health 'http://127.0.0.1:8000/health' 5
$apiOk = Wait-Health "http://127.0.0.1:$nodePort/health" 5
$webOk = Wait-Health 'http://127.0.0.1:3200/' 5
if ($pyOk)  { Ok  "  [OK] Python API  :8000" } else { Fail "  [X]  Python API  :8000" }
if ($apiOk) { Ok  "  [OK] Node API    :$nodePort" } else { Fail "  [X]  Node API    :$nodePort" }
if ($webOk) { Ok  "  [OK] Web         :3200" } else { Fail "  [X]  Web         :3200" }
Info ""
Info "  Dashboard : http://localhost:3200"
Info "  Docs API  : http://127.0.0.1:8000/docs"
Info "  Stop      : stop.bat"
Info ""
if ($webOk -and -not $NoBrowser) { Start-Process 'http://localhost:3200' | Out-Null }

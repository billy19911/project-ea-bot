# EA Bot - stop semua service (Python API, Node API, Web) pada port dari .env.runtime.
# Pakai: stop.bat (atau: npm run down)
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Load .env.runtime so stop uses the SAME non-default ports as start.
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
}
function EnvOr([string]$key, [string]$fallback) {
  if ($envMap.ContainsKey($key) -and $envMap[$key]) { return $envMap[$key] }
  return $fallback
}
$pyPort   = [int](EnvOr 'PY_PORT' '8787')
$nodePort = [int](EnvOr 'NODE_PORT' '3789')
$webPort  = [int](EnvOr 'WEB_PORT' '4321')

Write-Host "=== EA Bot - stop semua service ==="

function Stop-ServiceOnPort([int]$port, [string]$name) {
  $lines = netstat -ano | Select-String -Pattern 'LISTENING' | Select-String -Pattern ":$port\s"
  if (-not $lines) {
    Write-Host ("[{0}] port {1} - tidak ada proses" -f $name, $port) -ForegroundColor DarkGray
    return
  }
  $procIds = @()
  foreach ($l in $lines) {
    $parts = $l.ToString().Trim() -split '\s+'
    $procIds += $parts[$parts.Count - 1]
  }
  $procIds = $procIds | Sort-Object -Unique
  foreach ($procId in $procIds) {
    try {
      # WMI Terminate works even when Stop-Process hits "Access is denied"
      # (e.g. a process started from another elevated session).
      Invoke-CimMethod -InputObject (Get-CimInstance Win32_Process -Filter "ProcessId=$procId") -MethodName Terminate | Out-Null
      Write-Host ("[{0}] port {1} - PID {2} dihentikan" -f $name, $port, $procId) -ForegroundColor Yellow
    } catch {
      Write-Host ("[{0}] port {1} - GAGAL hentikan PID {2}: {3}" -f $name, $port, $procId, $_.Exception.Message) -ForegroundColor Red
    }
  }
}

Stop-ServiceOnPort $pyPort   'Python API'
Stop-ServiceOnPort $nodePort 'Node API'
Stop-ServiceOnPort $webPort  'Web'

Start-Sleep -Seconds 1
Write-Host "Selesai. Nyalakan lagi: start.bat" -ForegroundColor Green

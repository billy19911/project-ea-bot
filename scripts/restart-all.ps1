# EA Bot - restart semua service (stop lalu start). Satu klik: restart.bat
param([switch]$NoBrowser)
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "=== EA Bot - restart semua service ===" -ForegroundColor Cyan
Write-Host ""

# 1) Stop (uses the same .env.runtime ports as start).
& (Join-Path $PSScriptRoot 'stop-all.ps1')

Write-Host ""
Write-Host "Menunggu port benar-benar bebas..." -ForegroundColor DarkGray

# Load ports to know what to wait for.
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
$ports = @(
  [int](EnvOr 'PY_PORT' '8787'),
  [int](EnvOr 'NODE_PORT' '3789'),
  [int](EnvOr 'WEB_PORT' '4321')
)

# 2) Wait until no port is LISTENING (max ~15s).
$deadline = (Get-Date).AddSeconds(15)
do {
  $busy = $false
  foreach ($p in $ports) {
    if (netstat -ano | Select-String -Pattern 'LISTENING' | Select-String -Pattern ":$p\s") { $busy = $true }
  }
  if ($busy) { Start-Sleep -Milliseconds 500 }
} while ($busy -and (Get-Date) -lt $deadline)

Write-Host ""
# 3) Start.
& (Join-Path $PSScriptRoot 'start-all.ps1') @PSBoundParameters

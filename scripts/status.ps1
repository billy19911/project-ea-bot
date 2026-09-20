# EA Bot - status service (port dari .env.runtime).
# Pakai: status.bat (atau: npm run status)
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

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

function Show-Status([string]$name, [string]$url) {
  try {
    Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 4 | Out-Null
    Write-Host ("  [OK] {0,-12} {1}" -f $name, $url) -ForegroundColor Green
  } catch {
    Write-Host ("  [X]  {0,-12} {1}" -f $name, $url) -ForegroundColor Red
  }
}

Write-Host "=== EA Bot - status ==="
Show-Status 'Python API' "http://127.0.0.1:$pyPort/health"
Show-Status 'Node API'   "http://127.0.0.1:$nodePort/health"
Show-Status 'Web'        "http://127.0.0.1:$webPort/"
Write-Host ""
Write-Host "  Dashboard : http://localhost:$webPort" -ForegroundColor Cyan
Write-Host "  Docs API  : http://127.0.0.1:$pyPort/docs" -ForegroundColor Cyan

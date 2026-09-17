# EA Bot - status service.
# Pakai: status.bat (atau: npm run status)
$ProgressPreference = 'SilentlyContinue'

function Show-Status([string]$name, [string]$url) {
  try {
    $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 4
    Write-Host ("  [OK] {0,-12} {1}" -f $name, $url) -ForegroundColor Green
  } catch {
    Write-Host ("  [X]  {0,-12} {1}" -f $name, $url) -ForegroundColor Red
  }
}

Write-Host "=== EA Bot - status ==="
Show-Status 'Python API' 'http://127.0.0.1:8000/health'
Show-Status 'Node API'   'http://127.0.0.1:3001/health'
Show-Status 'Web'        'http://127.0.0.1:3200/'

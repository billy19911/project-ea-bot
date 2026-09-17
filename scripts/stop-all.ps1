# EA Bot - stop semua service (port 8000, 3001, 3200).
# Pakai: stop.bat (atau: npm run down)
$ErrorActionPreference = 'Continue'
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
      Stop-Process -Id ([int]$procId) -Force -ErrorAction Stop
      Write-Host ("[{0}] port {1} - PID {2} dihentikan" -f $name, $port, $procId) -ForegroundColor Yellow
    } catch {
      Write-Host ("[{0}] port {1} - GAGAL hentikan PID {2}: {3}" -f $name, $port, $procId, $_.Exception.Message) -ForegroundColor Red
    }
  }
}

Stop-ServiceOnPort 8000 'Python API'
Stop-ServiceOnPort 3001 'Node API'
Stop-ServiceOnPort 3200 'Web'

Start-Sleep -Seconds 1
Write-Host "Selesai. Nyalakan lagi: start.bat" -ForegroundColor Green

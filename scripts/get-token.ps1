# EA Bot - mint dev token & copy ke clipboard (untuk dashboard).
# Pakai: token.bat  (butuh Node API hidup + DEV_AUTH_ENABLED=true)
# Port dibaca dari .env.runtime (NODE_PORT/WEB_PORT; fallback 3789/4321).
# Flag: -Show (tampilkan token di layar juga)
param([switch]$Show)

$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot

# Muat .env.runtime (port non-default; gitignored)
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
$nodePort = if ($envMap['NODE_PORT']) { [int]$envMap['NODE_PORT'] } else { 3789 }
$webPort  = if ($envMap['WEB_PORT'])  { [int]$envMap['WEB_PORT'] }  else { 4321 }

$body = '{"userId":"operator","role":"admin"}'
try {
  $resp = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$nodePort/auth/token" `
    -ContentType 'application/json' -Body $body -TimeoutSec 8
  if (-not $resp.token) { throw 'respons tanpa token' }
  $copied = $false
  try { Set-Clipboard -Value $resp.token -ErrorAction Stop; $copied = $true } catch { }
  if ($copied) {
    Write-Host "[OK] Token admin dibuat & dicopy ke clipboard." -ForegroundColor Green
  } else {
    Write-Host "[OK] Token admin dibuat (clipboard tidak tersedia - jalankan ulang dengan -Show)." -ForegroundColor Yellow
  }
  if ($Show) {
    Write-Host ""
    Write-Host $resp.token
    Write-Host ""
  }
  Write-Host "Langkah pakai:"
  Write-Host "  1. Buka  http://localhost:$webPort/login"
  Write-Host "  2. Tempel token (Ctrl+V), lalu klik Masuk."
  Write-Host ""
  Write-Host "Tanpa script ini: klik 'Buat token dev (sekali klik)' di halaman /login."
} catch {
  Write-Host "[X] Gagal mint token: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host "    Pastikan Node API :$nodePort hidup dan DEV_AUTH_ENABLED=true."
}

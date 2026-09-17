# EA Bot - mint dev token & copy ke clipboard (untuk dashboard).
# Pakai: token.bat  (butuh Node API :3001 hidup + DEV_AUTH_ENABLED=true)
# Flag: -Show (tampilkan token di layar juga)
param([switch]$Show)

$ProgressPreference = 'SilentlyContinue'
$body = '{"userId":"operator","role":"admin"}'
try {
  $resp = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:3001/auth/token' `
    -ContentType 'application/json' -Body $body -TimeoutSec 8
  if (-not $resp.token) { throw 'respons tanpa token' }
  Set-Clipboard -Value $resp.token
  Write-Host "[OK] Token admin dibuat & dicopy ke clipboard." -ForegroundColor Green
  if ($Show) {
    Write-Host ""
    Write-Host $resp.token
    Write-Host ""
  }
  Write-Host "Langkah pakai (sekali saja per browser):"
  Write-Host "  1. Buka  http://localhost:3200"
  Write-Host "  2. Tekan F12 -> tab Console, jalankan:"
  Write-Host "     localStorage.setItem('ea-bot-token', await navigator.clipboard.readText()); location.reload()"
  Write-Host ""
  Write-Host "Kalau clipboard tidak bisa dibaca: token.bat -Show lalu salin manual."
} catch {
  Write-Host "[X] Gagal mint token: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host "    Pastikan Node API :3001 hidup dan DEV_AUTH_ENABLED=true."
}

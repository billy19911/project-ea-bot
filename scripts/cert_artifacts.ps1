<#
.SYNOPSIS
    CERT-A1 — CI/Artifacts generator for Production Certification Gate A.

.DESCRIPTION
    Runs REAL commands and writes their FULL output (never piped to head/tail)
    into ``reports/`` at the repository root. The Production Certification gate
    (Gate A) reads these artifacts from disk via
    ``services/python/src/live_readiness/certification_evidence.py``. Each file
    is written even when the underlying command fails — the honest exit code is
    recorded so the gate cannot fabricate a pass.

    Artifacts produced:
        reports/pytest-report.txt   pytest (services/python)
        reports/node_tests.json     npm test (project-ea-bot-api)
        reports/web_build.txt       npm run build (project-ea-bot-web)
        reports/typecheck.txt       tsc --noEmit (web + api)
        reports/lint.txt            flake8 + black + eslint (web + api)
        reports/security.json       pip-audit + npm audit

.PARAMETER Only
    Optional. Run only a subset of steps. Valid values:
    pytest, node_tests, web_build, typecheck, lint, security.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/cert_artifacts.ps1
#>
[CmdletBinding()]
param(
    [string[]]$Only = @()
)

$ErrorActionPreference = "Continue"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ReportsDir = Join-Path $RepoRoot "reports"
$PythonDir = Join-Path $RepoRoot "services/python"
$PythonExe = Join-Path $PythonDir ".venv/Scripts/python.exe"
$ApiDir = Join-Path $RepoRoot "apps/api"
$WebDir = Join-Path $RepoRoot "apps/web"

New-Item -ItemType Directory -Force -Path $ReportsDir | Out-Null

# UTF-8 without BOM — keeps JSON artifacts strictly valid.
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
function Write-Utf8NoBom {
    param([string]$Path, [string]$Content)
    [System.IO.File]::WriteAllText($Path, $Content, $Utf8NoBom)
}
function Add-Utf8NoBom {
    param([string]$Path, [string]$Content)
    [System.IO.File]::AppendAllText($Path, $Content, $Utf8NoBom)
}

function Test-StepSelected {
    param([string]$Name)
    if ($Only.Count -eq 0) { return $true }
    return ($Only -contains $Name)
}

function Write-Log {
    param([string]$Message)
    Write-Host ("[cert_artifacts] {0}" -f $Message)
}

# ---------------------------------------------------------------------------
# Run a command, capture FULL stdout+stderr, return @{ Output; ExitCode }.
# Never pipes to head/tail. Exit code recorded honestly, even on failure.
# ---------------------------------------------------------------------------
function ConvertTo-ArgString {
    # Quote every argument for Windows command-line parsing (handles spaces and
    # embedded double quotes). Works on Windows PowerShell 5.1.
    param([string[]]$Arguments)
    $parts = @()
    foreach ($a in $Arguments) {
        $s = [string]$a
        if ($s -match '[\s"]') {
            # Escape backslashes preceding a quote, then wrap in quotes.
            $s = $s -replace '(\\*)"', '$1$1\"'
            $s = $s -replace '(\\+)$', '$1$1'
            $parts += ('"' + $s + '"')
        } else {
            $parts += $s
        }
    }
    return ($parts -join " ")
}

function Resolve-Executable {
    # Resolve a command (bare name or path) to a path the .NET Process API can
    # actually launch. .ps1 shims (e.g. npm.ps1) cannot be started directly, so
    # we prefer a .cmd/.exe/.bat sibling of the same base name.
    param([string]$Name)

    # Already a real launchable binary.
    if ((Test-Path $Name) -and ($Name -match '\.(cmd|exe|bat)$')) { return $Name }

    # Determine the base name and the directory to search.
    $base = $Name
    $dir = $null
    if ($Name -match '[\\/]') {
        $dir = Split-Path $Name -Parent
        $base = [System.IO.Path]::GetFileNameWithoutExtension($Name)
    } else {
        $cmd = Get-Command $Name -ErrorAction SilentlyContinue
        if ($cmd) {
            $src = @($cmd)[0].Source
            if ($src -match '\.(cmd|exe|bat)$') { return $src }
            $dir = Split-Path $src -Parent
        }
    }

    # Prefer a sibling .cmd/.exe/.bat.
    if ($dir) {
        foreach ($ext in @(".cmd", ".exe", ".bat")) {
            $cand = Join-Path $dir ($base + $ext)
            if (Test-Path $cand) { return $cand }
        }
    }

    # Fall back to where.exe search across PATH.
    $where = & where.exe $base 2>$null
    if ($where) {
        foreach ($line in @($where)) {
            if ($line -match '\.(cmd|exe|bat)$') { return $line.Trim() }
        }
    }
    return $Name
}

function Invoke-NativeCapture {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory = $RepoRoot
    )
    $exe = Resolve-Executable -Name $FilePath
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $psi.Arguments = ConvertTo-ArgString -Arguments $Arguments
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    try {
        [void]$proc.Start()
        $stdout = $proc.StandardOutput.ReadToEnd()
        $stderr = $proc.StandardError.ReadToEnd()
        $proc.WaitForExit()
        $code = $proc.ExitCode
    } catch {
        return @{ Output = ("failed to start '{0}': {1}" -f $exe, $_.Exception.Message); ExitCode = -1 }
    } finally {
        if ($proc) { $proc.Dispose() }
    }
    $combined = $stdout
    if ($stderr -and $stderr.Length -gt 0) {
        $combined = $combined + "`n" + $stderr
    }
    return @{ Output = $combined; ExitCode = $code }
}

# Append a section header + full output + honest exit code to a text file.
function Add-TextSection {
    param(
        [string]$Path,
        [string]$Title,
        [string]$Command,
        [hashtable]$Result
    )
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.AppendLine(("=" * 78))
    [void]$sb.AppendLine("SECTION: $Title")
    [void]$sb.AppendLine("COMMAND: $Command")
    [void]$sb.AppendLine(("=" * 78))
    [void]$sb.AppendLine($Result.Output)
    [void]$sb.AppendLine("")
    [void]$sb.AppendLine("EXIT_CODE: $($Result.ExitCode)")
    [void]$sb.AppendLine("")
    Add-Utf8NoBom -Path $Path -Content $sb.ToString()
}

function New-TextArtifact {
    param([string]$Path, [string]$Header)
    if (Test-Path $Path) { Remove-Item $Path -Force }
    Write-Utf8NoBom -Path $Path -Content $Header
}

# Best-effort extraction of the JSON document from mixed tool output
# (pip-audit prints a human summary line before the JSON on some versions).
function Extract-Json {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $null }
    $trimmed = $Text.Trim()
    try { return ($trimmed | ConvertFrom-Json) } catch { }
    $objIdx = $trimmed.IndexOf("{")
    $arrIdx = $trimmed.IndexOf("[")
    $start = -1
    if ($objIdx -ge 0 -and $arrIdx -ge 0) { $start = [Math]::Min($objIdx, $arrIdx) }
    elseif ($objIdx -ge 0) { $start = $objIdx }
    elseif ($arrIdx -ge 0) { $start = $arrIdx }
    if ($start -lt 0) { return $null }
    $jsonText = $trimmed.Substring($start)
    try { return ($jsonText | ConvertFrom-Json) } catch { return $null }
}

# ---------------------------------------------------------------------------
# 1) pytest report -----------------------------------------------------------
# ---------------------------------------------------------------------------
if (Test-StepSelected "pytest") {
    $out = Join-Path $ReportsDir "pytest-report.txt"
    $cmd = "./.venv/Scripts/python.exe -m pytest -q"
    Write-Log "Running pytest (this can take 10-20 minutes)..."

    # pytest.ini sets --basetemp=./temp_pytest. Stale numbered dirs from a
    # previous run make pytest 9.x raise "is not a normalized and relative
    # path" on tmp_path fixtures. temp_pytest is a scratch dir (excluded by
    # the Gate A collector), so clearing it first is safe and keeps the run
    # deterministic.
    $baseTmp = Join-Path $PythonDir "temp_pytest"
    if (Test-Path $baseTmp) {
        Remove-Item -Recurse -Force $baseTmp -ErrorAction SilentlyContinue
    }

    if (Test-Path $PythonExe) {
        $res = Invoke-NativeCapture -FilePath $PythonExe `
            -Arguments @("-m", "pytest", "-q") -WorkingDirectory $PythonDir
    } else {
        $res = @{ Output = "python venv tidak ditemukan di $PythonExe"; ExitCode = -1 }
    }
    New-TextArtifact -Path $out -Header "CERT-A1 pytest report`nCOMMAND: $cmd`ncwd: services/python`n"
    Add-TextSection -Path $out -Title "pytest" -Command $cmd -Result $res
    Write-Log "pytest-report.txt written (exit=$($res.ExitCode))"
}

# ---------------------------------------------------------------------------
# 2) node tests report (JSON) ------------------------------------------------
# ---------------------------------------------------------------------------
if (Test-StepSelected "node_tests") {
    $out = Join-Path $ReportsDir "node_tests.json"
    $cmd = "npm test --workspace=project-ea-bot-api"
    Write-Log "Running Node API tests..."
    if (-not $npm) { $npm = "npm" }
    $res = Invoke-NativeCapture -FilePath $npm `
        -Arguments @("test", "--workspace=project-ea-bot-api") -WorkingDirectory $RepoRoot
    # If the "test" script is missing, fall back to "npm run test" as instructed.
    if ($res.ExitCode -ne 0 -and $res.Output -match "Missing script" ) {
        $cmd = "npm run test --workspace=project-ea-bot-api"
        $res = Invoke-NativeCapture -FilePath $npm `
            -Arguments @("run", "test", "--workspace=project-ea-bot-api") -WorkingDirectory $RepoRoot
    }
    $payload = [ordered]@{
        command   = $cmd
        exit_code = $res.ExitCode
        output    = $res.Output
    }
    Write-Utf8NoBom -Path $out -Content ($payload | ConvertTo-Json -Depth 5)
    Write-Log "node_tests.json written (exit=$($res.ExitCode))"
}

# ---------------------------------------------------------------------------
# 3) web build log -----------------------------------------------------------
# ---------------------------------------------------------------------------
if (Test-StepSelected "web_build") {
    $out = Join-Path $ReportsDir "web_build.txt"
    $cmd = "npm run build --workspace=project-ea-bot-web"
    Write-Log "Running web build..."
    if (-not $npm) { $npm = "npm" }
    $res = Invoke-NativeCapture -FilePath $npm `
        -Arguments @("run", "build", "--workspace=project-ea-bot-web") -WorkingDirectory $RepoRoot
    New-TextArtifact -Path $out -Header "CERT-A1 web build report`nCOMMAND: $cmd`n"
    Add-TextSection -Path $out -Title "web build" -Command $cmd -Result $res
    Write-Log "web_build.txt written (exit=$($res.ExitCode))"
}

# ---------------------------------------------------------------------------
# 4) type-check log ----------------------------------------------------------
# ---------------------------------------------------------------------------
if (Test-StepSelected "typecheck") {
    $out = Join-Path $ReportsDir "typecheck.txt"
    New-TextArtifact -Path $out -Header "CERT-A1 type-check report`n"

    if (-not $npm) { $npm = "npm" }
    if (-not $npx) { $npx = "npx" }

    # Web: prefer the workspace typecheck script, else npx tsc --noEmit in apps/web.
    $webPkg = Join-Path $WebDir "package.json"
    $hasWebTypecheck = $false
    if (Test-Path $webPkg) {
        $hasWebTypecheck = ((Get-Content $webPkg -Raw) -match '"typecheck"\s*:')
    }
    if ($hasWebTypecheck) {
        $cmd = "npm run typecheck --workspace=project-ea-bot-web"
        $res = Invoke-NativeCapture -FilePath $npm `
            -Arguments @("run", "typecheck", "--workspace=project-ea-bot-web") -WorkingDirectory $RepoRoot
    } else {
        $cmd = "npx tsc --noEmit (cwd apps/web)"
        $res = Invoke-NativeCapture -FilePath $npx `
            -Arguments @("tsc", "--noEmit") -WorkingDirectory $WebDir
    }
    Add-TextSection -Path $out -Title "web type-check" -Command $cmd -Result $res

    # API: npx tsc --noEmit in apps/api.
    $cmdApi = "npx tsc --noEmit (cwd apps/api)"
    $resApi = Invoke-NativeCapture -FilePath $npx `
        -Arguments @("tsc", "--noEmit") -WorkingDirectory $ApiDir
    Add-TextSection -Path $out -Title "api type-check" -Command $cmdApi -Result $resApi

    Write-Log "typecheck.txt written (web=$($res.ExitCode), api=$($resApi.ExitCode))"
}

# ---------------------------------------------------------------------------
# 5) lint log ----------------------------------------------------------------
# ---------------------------------------------------------------------------
if (Test-StepSelected "lint") {
    $out = Join-Path $ReportsDir "lint.txt"
    New-TextArtifact -Path $out -Header "CERT-A1 lint report`n"

    if (Test-Path $PythonExe) {
        # flake8
        $cmdF = "./.venv/Scripts/python.exe -m flake8 --max-line-length=100 --extend-ignore=E203,W503 src"
        $resF = Invoke-NativeCapture -FilePath $PythonExe `
            -Arguments @("-m", "flake8", "--max-line-length=100", "--extend-ignore=E203,W503", "src") `
            -WorkingDirectory $PythonDir
        Add-TextSection -Path $out -Title "flake8 (services/python)" -Command $cmdF -Result $resF

        # black --check
        $cmdB = "./.venv/Scripts/python.exe -m black --check src"
        $resB = Invoke-NativeCapture -FilePath $PythonExe `
            -Arguments @("-m", "black", "--check", "src") -WorkingDirectory $PythonDir
        Add-TextSection -Path $out -Title "black --check (services/python)" -Command $cmdB -Result $resB
    } else {
        Add-TextSection -Path $out -Title "flake8 (services/python)" `
            -Command "./.venv/Scripts/python.exe -m flake8 ..." `
            -Result @{ Output = "python venv tidak ditemukan di $PythonExe"; ExitCode = -1 }
    }

    if (-not $npm) { $npm = "npm" }

    $cmdWebLint = "npm run lint --workspace=project-ea-bot-web"
    $resWebLint = Invoke-NativeCapture -FilePath $npm `
        -Arguments @("run", "lint", "--workspace=project-ea-bot-web") -WorkingDirectory $RepoRoot
    Add-TextSection -Path $out -Title "eslint (web)" -Command $cmdWebLint -Result $resWebLint

    $cmdApiLint = "npm run lint --workspace=project-ea-bot-api"
    $resApiLint = Invoke-NativeCapture -FilePath $npm `
        -Arguments @("run", "lint", "--workspace=project-ea-bot-api") -WorkingDirectory $RepoRoot
    Add-TextSection -Path $out -Title "eslint (api)" -Command $cmdApiLint -Result $resApiLint

    Write-Log "lint.txt written"
}

# ---------------------------------------------------------------------------
# 6) security report (JSON) --------------------------------------------------
# ---------------------------------------------------------------------------
if (Test-StepSelected "security") {
    $out = Join-Path $ReportsDir "security.json"
    Write-Log "Running security scans (pip-audit + npm audit)..."

    # pip-audit -f json (cwd services/python). pip-audit prints a human summary
    # to stderr and the JSON to stdout, so we also write a clean JSON copy via
    # -o to a temp file (the most reliable source of truth).
    $pipAudit = $null
    if (Test-Path $PythonExe) {
        $tmpJson = Join-Path ([System.IO.Path]::GetTempPath()) ("cert_a1_pipaudit_{0}.json" -f $PID)
        $resPip = Invoke-NativeCapture -FilePath $PythonExe `
            -Arguments @("-m", "pip_audit", "-f", "json", "-o", $tmpJson) -WorkingDirectory $PythonDir
        if ($resPip.ExitCode -eq -1 -or $resPip.Output -match "No module named .*pip_audit") {
            $pipAudit = [ordered]@{ error = "not installed"; exit_code = -1 }
        } else {
            $parsed = $null
            if (Test-Path $tmpJson) {
                try { $parsed = Extract-Json -Text (Get-Content $tmpJson -Raw) } catch { $parsed = $null }
            }
            if ($parsed -eq $null) { $parsed = Extract-Json -Text $resPip.Output }
            if ($parsed -ne $null) {
                $pipAudit = [ordered]@{
                    command   = "pip-audit -f json"
                    exit_code = $resPip.ExitCode
                    findings  = $parsed
                }
            } else {
                $pipAudit = [ordered]@{
                    command   = "pip-audit -f json"
                    exit_code = $resPip.ExitCode
                    output    = $resPip.Output
                }
            }
            if (Test-Path $tmpJson) { Remove-Item $tmpJson -Force -ErrorAction SilentlyContinue }
        }
    } else {
        $pipAudit = [ordered]@{ error = "not installed"; exit_code = -1 }
    }

    # npm audit --json (root)
    $resNpm = Invoke-NativeCapture -FilePath "npm" -Arguments @("audit", "--json") -WorkingDirectory $RepoRoot
    $npmParsed = Extract-Json -Text $resNpm.Output
    if ($npmParsed -ne $null) {
        $npmAudit = [ordered]@{
            command   = "npm audit --json"
            exit_code = $resNpm.ExitCode
            findings  = $npmParsed
        }
    } else {
        $npmAudit = [ordered]@{
            command   = "npm audit --json"
            exit_code = $resNpm.ExitCode
            output    = $resNpm.Output
        }
    }

    $payload = [ordered]@{
        pip_audit = $pipAudit
        npm_audit = $npmAudit
    }
    Write-Utf8NoBom -Path $out -Content ($payload | ConvertTo-Json -Depth 20)
    Write-Log "security.json written"
}

Write-Log "Done. Artifacts in $ReportsDir"
Get-ChildItem -Path $ReportsDir -File | ForEach-Object {
    Write-Log ("  {0}  ({1} bytes)" -f $_.Name, $_.Length)
}

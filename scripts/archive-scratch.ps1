<#
.SYNOPSIS
    Archive throwaway session artifacts (audit probes, recon dumps, ad-hoc
    investigation files) out of the repository root and services/python/.

.DESCRIPTION
    During long debugging/audit sessions a large number of one-off files
    accumulate at the repo root and in services/python/ — files named with a
    leading underscore (`_q12.txt`), or with the `b4_` / `recon_` prefixes.
    None of these are source code; they are scratch output.

    This script MOVES them (never deletes) into
        archive/scratch-<yyyyMM>/<original relative path>
    so the repo stays tidy while everything remains recoverable.

    It is safe by construction: it refuses to move real Python source
    (anything under services/python/src/, and any `__init__.py`), and it
    skips dependency/build directories.

    `archive/` is gitignored, so archived files disappear from `git status`.

.PARAMETER DryRun
    Print what would be moved without moving anything.

.PARAMETER WhatIf
    Standard PowerShell -WhatIf support (alias).

.EXAMPLE
    pwsh -File scripts/archive-scratch.ps1 -DryRun
    pwsh -File scripts/archive-scratch.ps1
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

# Resolve repo root (this script lives in <root>/scripts).
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Stamp = Get-Date -Format 'yyyyMM'
$ArchiveRoot = Join-Path $RepoRoot "archive/scratch-$Stamp"

# Directories that must NEVER be touched.
$SkipDirRegex = '(^|[\\/])(node_modules|\.venv|venv|\.next[^\\/]*|__pycache__|\.git|archive|\.pytest_cache|dist|build)([\\/]|$)'

# Real source that must NEVER be archived even though it starts with '_'.
$ProtectedRegex = 'services[\\/]python[\\/]src[\\/]|(^|[\\/])__init__\.py$|(^|[\\/])__main__\.py$'

function Get-RelativePath {
    param([string]$Base, [string]$Full)
    $baseUri = [System.Uri]((Resolve-Path $Base).Path + [System.IO.Path]::DirectorySeparatorChar)
    $fullUri = [System.Uri](Resolve-Path $Full).Path
    return [System.Uri]::UnescapeDataString($baseUri.MakeRelativeUri($fullUri).ToString()).Replace('/', [System.IO.Path]::DirectorySeparatorChar)
}

# Collect candidate files: scratch patterns at repo root and in services/python.
$patterns = @(
    '_*', 'b4_*', 'recon_*', '_dump*', '_probe*', '_recon*', '_fullsuite*',
    '_sym*', '_t?.txt', 'git_log.txt', 'git_status.txt'
)

$candidates = New-Object System.Collections.Generic.List[string]

# 1) Repo root (files only, no recursion).
foreach ($p in $patterns) {
    Get-ChildItem -Path $RepoRoot -Filter $p -File -ErrorAction SilentlyContinue |
        ForEach-Object { $candidates.Add($_.FullName) }
}

# 2) services/python (files only, no recursion) — the other main dump site.
$PyRoot = Join-Path $RepoRoot 'services/python'
if (Test-Path $PyRoot) {
    foreach ($p in $patterns) {
        Get-ChildItem -Path $PyRoot -Filter $p -File -ErrorAction SilentlyContinue |
            ForEach-Object { $candidates.Add($_.FullName) }
    }
}

# 3) The known scratch subfolder, if present.
# NOTE: services/python/temp_pytest/ is pytest scratch output and is already
# gitignored; we leave it alone so the archive only captures root-level clutter
# (moving thousands of pytest temp dirs would just bloat the archive).

$candidates = $candidates | Sort-Object -Unique

$moved = 0
$skipped = 0

foreach ($file in $candidates) {
    $rel = Get-RelativePath -Base $RepoRoot -Full $file

    if ($rel -match $SkipDirRegex) { $skipped++; continue }
    if ($rel -match $ProtectedRegex) {
        Write-Verbose "Protected (real source), skipping: $rel"
        $skipped++
        continue
    }

    $dest = Join-Path $ArchiveRoot $rel
    $destDir = Split-Path -Parent $dest

    if ($DryRun -or $WhatIfPreference) {
        Write-Host "[dry-run] $rel  ->  archive/scratch-$Stamp/$rel" -ForegroundColor DarkGray
        $moved++
        continue
    }

    if (-not (Test-Path $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }
    Move-Item -LiteralPath $file -Destination $dest -Force
    $moved++
}

Write-Host ''
if ($DryRun) {
    Write-Host "DRY RUN: would archive $moved file(s); $skipped skipped." -ForegroundColor Cyan
} else {
    Write-Host "Archived $moved file(s) to archive/scratch-$Stamp/; $skipped skipped." -ForegroundColor Green
}

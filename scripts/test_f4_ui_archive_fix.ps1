param(
    [Parameter(Mandatory=$true)]
    [string]$ExpectedHead
)

$ErrorActionPreference = "Stop"

$wt = "D:\program\lpz-risk-system_ui_fix_test"
$python = "D:\program\lpz-risk-system_dev\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $wt)) {
    throw "UI test worktree missing: $wt"
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python missing: $python"
}

$gitArgs = @(
    "-c", "safe.directory=$wt",
    "-c", "maintenance.auto=false",
    "-c", "gc.auto=0",
    "-C", $wt
)

$head = (@(& git @gitArgs rev-parse HEAD) -join "").Trim()
if ($LASTEXITCODE -ne 0) {
    throw "HEAD check FAILED"
}
if ($head -ne $ExpectedHead) {
    throw "Unexpected UI fix HEAD: $head"
}

$dirty = @(& git @gitArgs status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw "Worktree status FAILED"
}
if ($dirty.Count -gt 0) {
    $dirty | ForEach-Object { Write-Host $_ }
    throw "UI test worktree has local changes"
}

Set-Location $wt
$oldPythonPath = $env:PYTHONPATH

try {
    $env:PYTHONPATH = @(
        $wt,
        (Join-Path $wt "src")
    ) -join [IO.Path]::PathSeparator

    Write-Host "===== PYTHON IMPORT PROOF =====" -ForegroundColor Cyan

    $importCode = @"
import sys
import lpz_risk
import lpz_risk.radar_geographic_envelope as r
print("python =", sys.executable)
print("lpz_risk =", lpz_risk.__file__)
print("radar_geographic_envelope =", r.__file__)
"@

    & $python -c $importCode

    if ($LASTEXITCODE -ne 0) {
        throw "Worktree Python import proof FAILED"
    }

    Write-Host ""
    Write-Host "===== REGRESSION TESTS =====" -ForegroundColor Cyan

    $pytestArgs = @(
        "-m", "pytest", "-q",
        "tests/test_field_motion_dashboard_contract.py",
        "tests/test_f4_archive_ui_regression.py",
        "tests/test_public_web.py",
        "tests/test_publish_f4_archived_research_summary.py",
        "tests/test_publish_latest_f4_geographic_research.py",
        "tests/test_publish_f4_field_motion_research.py"
    )

    & $python @pytestArgs

    if ($LASTEXITCODE -ne 0) {
        throw "Regression tests FAILED"
    }

    Write-Host ""
    Write-Host "===== JAVASCRIPT SYNTAX =====" -ForegroundColor Cyan

    foreach ($js in @(
        "web/js/map.js",
        "web/js/app.js",
        "web/js/f4-archive.js"
    )) {
        node --check $js

        if ($LASTEXITCODE -ne 0) {
            throw "$js syntax FAILED"
        }
    }

    Write-Host ""
    Write-Host "===== F4 UI FIX STATIC TESTS COMPLETE =====" -ForegroundColor Green
}
finally {
    $env:PYTHONPATH = $oldPythonPath
}

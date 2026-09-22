param(
    [string]$CohortRoot = "D:\program\lpz-risk-system_f4_9c_cohort",
    [string]$Repo = "D:\program\lpz-risk-system_dev",
    [string]$PublishWt = "D:\program\lpz-risk-system_f4_dashboard_publish",
    [string]$PythonExe = "D:\program\lpz-risk-system_dev\.venv\Scripts\python.exe",
    [string]$DecisionJson = "",
    [switch]$Push
)

$ErrorActionPreference = "Stop"

# This is a one-shot, explicitly initiated display-only publisher.
# It never invokes F4-9C cycles, reads verification rows or opens skill,
# modifies the user's dirty main worktree, or changes Scheduled Tasks.

$TargetRel = "web/data/research/f4_field_motion_research.geojson"
$TargetBranch = "main"

if (-not (Test-Path -LiteralPath $CohortRoot -PathType Container)) {
    throw "F4-9C cohort not found: $CohortRoot"
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Publisher Python not found: $PythonExe"
}
if (-not (Test-Path -LiteralPath $Repo -PathType Container)) {
    throw "Repository not found: $Repo"
}
if ($DecisionJson -and -not (Test-Path -LiteralPath $DecisionJson -PathType Leaf)) {
    throw "Decision artifact not found: $DecisionJson"
}

Write-Host "===== F4-9C RESEARCH DASHBOARD PUBLICATION =====" -ForegroundColor Cyan
Write-Host "Cohort: $CohortRoot"
Write-Host "Main worktree will NOT be changed: $Repo"

git -C $Repo -c maintenance.auto=false fetch origin $TargetBranch
if ($LASTEXITCODE -ne 0) { throw "origin/main fetch FAILED" }

if (-not (Test-Path -LiteralPath $PublishWt)) {
    git -C $Repo -c maintenance.auto=false worktree add --detach $PublishWt origin/main
    if ($LASTEXITCODE -ne 0) { throw "Publication worktree creation FAILED" }
}
if (-not (Test-Path -LiteralPath (Join-Path $PublishWt ".git"))) {
    throw "Publication directory exists but is not a Git worktree: $PublishWt"
}

function Invoke-PublicationGit {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
    $result = & git -c "safe.directory=$PublishWt" -c maintenance.auto=false -c gc.auto=0 -C $PublishWt @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Publication Git command FAILED: $($GitArgs -join ' ')"
    }
    return $result
}

$Dirty = @(Invoke-PublicationGit status --porcelain)
$Unexpected = @($Dirty | Where-Object {
    $_ -and $_.Length -ge 4 -and $_.Substring(3) -ne $TargetRel
})
if ($Unexpected.Count -gt 0) {
    throw "Publication worktree contains unrelated changes; refusing overwrite: $($Unexpected -join '; ')"
}
# A previously generated dry-run GeoJSON may be present. No other dirty files
# are accepted; the only allowed path is regenerated from the frozen case.

# Detached HEAD returns no output; join converts an empty pipeline into "".
$CurrentBranch = (@(Invoke-PublicationGit branch --show-current) -join "").Trim()
if ($CurrentBranch -eq "") {
    Invoke-PublicationGit checkout -B f4-field-motion-publication | Out-Null
}
elseif ($CurrentBranch -ne "f4-field-motion-publication") {
    throw "Publication worktree is on unexpected branch: $CurrentBranch"
}

Invoke-PublicationGit merge --ff-only origin/main | Out-Null

$Publisher = Join-Path $PublishWt "scripts\publish_f4_field_motion_research.py"
if (-not (Test-Path -LiteralPath $Publisher -PathType Leaf)) {
    throw "Research publisher missing: $Publisher"
}
$Output = Join-Path $PublishWt "web\data\research\f4_field_motion_research.geojson"
$OldPythonPath = $env:PYTHONPATH

try {
    $env:PYTHONPATH = Join-Path $PublishWt "src"
    $argsPython = @(
        $Publisher,
        "--cohort-root", $CohortRoot,
        "--output", $Output,
        "--max-age-minutes", "90"
    )
    if ($DecisionJson) {
        $argsPython += @("--decision-json", $DecisionJson)
    }
    & $PythonExe @argsPython
    if ($LASTEXITCODE -ne 0) { throw "Field-motion GeoJSON export FAILED" }
}
finally {
    $env:PYTHONPATH = $OldPythonPath
}

$Doc = Get-Content -LiteralPath $Output -Raw -Encoding UTF8 |
    ConvertFrom-Json -DateKind String

if (
    $Doc.product -ne "LPZ_F4_FIELD_MOTION_RESEARCH" -or
    $Doc.research_only -ne $true -or
    $Doc.validated_forecast -ne $false -or
    $Doc.production_integration_enabled -ne $false -or
    $Doc.risk_engine_allowed -ne $false -or
    $Doc.lpz_forecast_generated -ne $false -or
    $Doc.probability_generated -ne $false -or
    $Doc.severity_generated -ne $false
) {
    throw "Research-only publication contract FAILED"
}
if ($Doc.status -notin @("AVAILABLE", "ARCHIVED")) {
    throw "No publishable frozen F4-9C geometry: $($Doc.status)"
}
if ($Doc.feature_count -le 0 -or $Doc.feature_count -ne @($Doc.features).Count) {
    throw "No valid component envelopes to publish"
}
if ($Doc.terminal_decision -notin @("PENDING", "GO", "NO_GO")) {
    throw "Unknown F4-9D decision"
}

Write-Host "===== READ-ONLY SCIENTIFIC PUBLICATION PROOF =====" -ForegroundColor Green
[PSCustomObject]@{
    CaseId = $Doc.source_case_id
    SourceAsOfUtc = $Doc.source_as_of_utc
    Status = $Doc.status
    HistoricalResearch = $Doc.historical_research
    Decision = $Doc.terminal_decision
    Features = $Doc.feature_count
    DistinctComponents = $Doc.projected_component_count
    RiskEngineAllowed = $Doc.risk_engine_allowed
} | Format-List

$Change = Invoke-PublicationGit status --porcelain -- $TargetRel
if (-not $Change) {
    Write-Host "No changed research geometry. Nothing to commit." -ForegroundColor Green
    exit 0
}
if (-not $Push) {
    Write-Host "DRY RUN: generated in isolated worktree; not committed/pushed." -ForegroundColor Yellow
    Write-Host "Re-run with -Push after reviewing the operational counts above."
    exit 0
}

Invoke-PublicationGit add -- $TargetRel | Out-Null
Invoke-PublicationGit commit -m "data: publish frozen F4 field-motion research envelopes" | Out-Host
Invoke-PublicationGit push origin "HEAD:refs/heads/main" | Out-Host

Write-Host "===== F4 RESEARCH PUBLICATION PUSHED =====" -ForegroundColor Green
Write-Host "GitHub Pages deployment must pass before calling this published."

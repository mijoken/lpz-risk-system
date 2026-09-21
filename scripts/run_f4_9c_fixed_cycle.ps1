param()

$ErrorActionPreference = "Stop"

$FixedSha     = "6ed115f630ee55ecebd68c4c8001133f762c07a4"
$RunnerWt     = "D:\program\lpz-risk-system_f4_9c_runner"
$ResearchVenv = "D:\program\lpz-risk-system_f4_9b_venv"
$CohortRoot   = "D:\program\lpz-risk-system_f4_9c_cohort"

$ResearchPython = Join-Path $ResearchVenv "Scripts\python.exe"
$StatusPath = Join-Path $CohortRoot "cohort_status.json"

if (-not (Test-Path -LiteralPath $RunnerWt)) {
    throw "F4-9C fixed runner worktree missing: $RunnerWt"
}

if (-not (Test-Path -LiteralPath $ResearchPython)) {
    throw "F4-9C research Python missing: $ResearchPython"
}

$Head = (git -C $RunnerWt rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "F4-9C fixed runner HEAD check failed"
}
if ($Head -ne $FixedSha) {
    throw "F4-9C fixed runner moved: expected $FixedSha got $Head"
}

$Dirty = git -C $RunnerWt status --porcelain
if ($LASTEXITCODE -ne 0) {
    throw "F4-9C fixed runner status check failed"
}
if ($Dirty) {
    throw "F4-9C fixed runner worktree is dirty"
}

if (Test-Path -LiteralPath $StatusPath) {
    $Status = Get-Content -LiteralPath $StatusPath -Raw -Encoding UTF8 |
        ConvertFrom-Json -DateKind String

    if (
        $Status.state -eq "READY_FOR_F4_9D_TARGET_MET" -or
        $Status.state -eq "READY_FOR_F4_9D_DEADLINE"
    ) {
        Write-Host "F4-9C SKIP: cohort is already ready for F4-9D."
        exit 0
    }
}

$env:PYTHONPATH = Join-Path $RunnerWt "src"
$CycleScript = Join-Path $RunnerWt "scripts\run_f4_9c_cycle.py"

if (-not (Test-Path -LiteralPath $CycleScript)) {
    throw "F4-9C cycle script missing from fixed worktree: $CycleScript"
}

& $ResearchPython $CycleScript --cohort-root $CohortRoot
$CycleExit = $LASTEXITCODE

if ($CycleExit -ne 0) {
    throw "F4-9C fixed cycle failed. exit=$CycleExit"
}

if (-not (Test-Path -LiteralPath $StatusPath)) {
    throw "F4-9C cohort status missing after cycle"
}

$Status = Get-Content -LiteralPath $StatusPath -Raw -Encoding UTF8 |
    ConvertFrom-Json -DateKind String

if ($Status.interim_skill_summary_emitted -ne $false) {
    throw "F4-9C anti-peeking invariant violated"
}
if ($Status.parameter_tuning_performed -ne $false) {
    throw "F4-9C parameter-tuning invariant violated"
}
if ($Status.risk_engine_allowed -ne $false) {
    throw "F4-9C Risk Engine invariant violated"
}

Write-Host (
    "F4-9C STATUS: state={0}; cases={1}; verified={2}; pending={3}; " +
    "verified_comparisons={4}; pending_comparisons={5}; slots={6}"
) -f @(
    $Status.state,
    $Status.case_count,
    $Status.verified_case_count,
    $Status.pending_case_count,
    $Status.verified_comparison_count,
    $Status.pending_planned_comparison_count,
    $Status.verified_plus_pending_distinct_slot_count
)

exit 0

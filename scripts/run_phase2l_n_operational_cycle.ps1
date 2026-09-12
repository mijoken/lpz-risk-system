param(
    [int]$HealthRefreshSeconds = 3300
)

$ErrorActionPreference = "Stop"

$Repo = "D:\program\lpz-risk-system_dev"
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$HealthScript = Join-Path $Repo "scripts\phase2l_l_source_health.py"
$CollectorScript = Join-Path $Repo "scripts\phase2l_m_local_prospective_collector.py"
$HealthReport = Join-Path $Repo "local_data\phase2l_l_source_health\phase2l_l_source_health_report.json"
$StateRoot = Join-Path $Repo "local_data\phase2l_n_scheduler"
$LogRoot = Join-Path $StateRoot "logs"
$LockPath = Join-Path $StateRoot "phase2l_n.lock"

New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null

$logDate = Get-Date -Format "yyyy-MM-dd"
$LogPath = Join-Path $LogRoot "$logDate.log"

function Write-PhaseLog {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Message"
    Write-Host $line
    Add-Content -Path $LogPath -Value $line -Encoding UTF8
}

$lockStream = $null
try {
    try {
        $lockStream = [System.IO.File]::Open(
            $LockPath,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
    }
    catch {
        Write-PhaseLog "SKIP: another Phase 2L-N cycle is still running."
        exit 0
    }

    foreach ($p in @($Python, $HealthScript, $CollectorScript)) {
        if (-not (Test-Path $p)) {
            throw "Required path not found: $p"
        }
    }

    Set-Location $Repo
    Write-PhaseLog "Phase 2L-N operational cycle START"

    $refreshHealth = $true
    $healthAge = $null

    if (Test-Path $HealthReport) {
        try {
            $health = Get-Content -Raw -Path $HealthReport -Encoding UTF8 | ConvertFrom-Json
            $generated = [DateTimeOffset]::Parse([string]$health.generated_at_utc)
            $healthAge = [int]([DateTimeOffset]::UtcNow - $generated).TotalSeconds

            if (
                $health.gate -eq "PASS_PHASE2L_L_SOURCE_HEALTH_OPERATIONAL_READINESS" -and
                $health.summary.operational_source_ready -eq $true -and
                $health.summary.risk_engine_allowed -eq $false -and
                $healthAge -lt $HealthRefreshSeconds
            ) {
                $refreshHealth = $false
            }
        }
        catch {
            Write-PhaseLog "Existing health report could not be trusted; refreshing it."
            $refreshHealth = $true
        }
    }

    if ($refreshHealth) {
        if ($null -eq $healthAge) {
            Write-PhaseLog "Refreshing Phase 2L-L source health (missing/unusable report)."
        }
        else {
            Write-PhaseLog "Refreshing Phase 2L-L source health (age=${healthAge}s; threshold=${HealthRefreshSeconds}s)."
        }

        & $Python $HealthScript
        $healthExit = $LASTEXITCODE

        if ($healthExit -ne 0) {
            Write-PhaseLog "SAFE STOP: Phase 2L-L source health failed/reviewed; collector NOT run. exit=$healthExit"
            exit $healthExit
        }

        Write-PhaseLog "Phase 2L-L source health PASS."
    }
    else {
        Write-PhaseLog "Reusing fresh Phase 2L-L source health (age=${healthAge}s)."
    }

    & $Python $CollectorScript
    $collectorExit = $LASTEXITCODE

    if ($collectorExit -ne 0) {
        Write-PhaseLog "SAFE STOP: Phase 2L-M collector failed; no operational risk output produced. exit=$collectorExit"
        exit $collectorExit
    }

    Write-PhaseLog "Phase 2L-M collector PASS."
    Write-PhaseLog "Phase 2L-N operational cycle COMPLETE."
    exit 0
}
catch {
    Write-PhaseLog ("FAIL: " + $_.Exception.Message)
    exit 2
}
finally {
    if ($null -ne $lockStream) {
        $lockStream.Dispose()
    }
}

param(
    [string]$TaskName = "LPZ-Prospective-Collector-15min",
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"

$Repo = "D:\program\lpz-risk-system_dev"
$Runner = Join-Path $Repo "scripts\run_phase2l_n_operational_cycle.ps1"

if (-not (Test-Path $Runner)) {
    throw "Runner not found: $Runner"
}

$Pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source
$Identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$UserSid = $Identity.User.Value

$Start = (Get-Date).Date.AddMinutes(4)
$StartBoundary = $Start.ToString("yyyy-MM-dd'T'HH:mm:ss")

$Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`""

$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>LPZ Phase 2L-N local prospective collector every 15 minutes.</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>$StartBoundary</StartBoundary>
      <Enabled>true</Enabled>
      <Repetition>
        <Interval>PT15M</Interval>
        <Duration>P1D</Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$UserSid</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$Pwsh</Command>
      <Arguments>$Arguments</Arguments>
      <WorkingDirectory>$Repo</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

Register-ScheduledTask `
    -TaskName $TaskName `
    -Xml $xml `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
$info = Get-ScheduledTaskInfo -TaskName $TaskName

Write-Host ""
Write-Host "========================================================================================================"
Write-Host "LPZ PHASE 2L-N — WINDOWS TASK SCHEDULER REGISTRATION"
Write-Host "========================================================================================================"
Write-Host "Task name        : $TaskName"
Write-Host "State            : $($task.State)"
Write-Host "PowerShell       : $Pwsh"
Write-Host "Runner           : $Runner"
Write-Host "Start boundary   : $StartBoundary"
Write-Host "Cadence          : every 15 minutes"
Write-Host "Multiple instance: IgnoreNew"
Write-Host "Network required : true"
Write-Host "Run context      : current user / InteractiveToken"
Write-Host "Last run time    : $($info.LastRunTime)"
Write-Host "Last task result : $($info.LastTaskResult)"
Write-Host "Next run time    : $($info.NextRunTime)"
Write-Host "========================================================================================================"

if ($RunNow) {
    Write-Host ""
    Write-Host "Starting one immediate scheduler smoke test..."
    Start-ScheduledTask -TaskName $TaskName

    $deadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 3
        $task = Get-ScheduledTask -TaskName $TaskName
        if ($task.State -ne "Running") {
            break
        }
    } while ((Get-Date) -lt $deadline)

    $info = Get-ScheduledTaskInfo -TaskName $TaskName

    Write-Host ""
    Write-Host "Smoke test state  : $($task.State)"
    Write-Host "Last run time     : $($info.LastRunTime)"
    Write-Host "Last task result  : $($info.LastTaskResult)"
    Write-Host "Next run time     : $($info.NextRunTime)"

    if ($task.State -eq "Running") {
        Write-Warning "Task is still running after the smoke-test observation window. Check the Phase 2L-N log."
        exit 0
    }

    if ($info.LastTaskResult -ne 0) {
        Write-Error "Scheduled smoke test returned non-zero result: $($info.LastTaskResult)"
        exit 2
    }

    Write-Host "Scheduler smoke test: PASS"
}

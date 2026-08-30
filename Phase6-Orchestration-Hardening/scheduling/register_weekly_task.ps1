# Registers one Windows Task Scheduler job per product, running
# `pulse run --product <name> --env production` every Saturday morning.
#
# NOT run automatically by anything in this repo - review it, then run it
# yourself when you're ready to schedule real weekly runs. Registering a
# scheduled task is a real, persistent change to this machine (it will
# trigger real pipeline runs - real LLM spend, and per the current
# environments.yaml, a real email to every configured stakeholder, every
# week, unattended) and deliberately isn't something automation should do
# without you looking at it first.
#
# This does NOT replace manual triggering - `pulse run --product <name>`
# still works exactly the same, any time, from a normal terminal. The two
# are not exclusive: both ultimately call the same ledger-gated
# `run_pipeline`, so a manual run and this Saturday trigger for the same
# (product, week) just make the second one a no-op, whichever happens
# first - see orchestrator/run.py's in-flight guard and ledger check.
#
# EdgeCases/Phase6-Orchestration-Hardening.md #2: Windows Task Scheduler
# triggers are evaluated in the machine's LOCAL time zone, not IST. This
# script asks Task Scheduler for 07:00 in whatever time zone Windows itself
# is set to and does NOT convert from IST for you - if this machine isn't
# set to IST, either change the machine's time zone or adjust -At below to
# the local-time equivalent of Saturday 07:00 IST yourself, and re-verify
# after any daylight-saving change.
#
# EdgeCases/Phase6-Orchestration-Hardening.md #9: all 6 products are
# staggered 15 minutes apart below (rather than firing simultaneously) -
# a real run takes 5-8 minutes end to end (real ingestion + embeddings +
# clustering are CPU-bound), so a short stagger would still overlap
# multiple heavy pipelines on one local machine. Adjust if you add more
# products or move this to a beefier/cloud host.
#
# Each product's scheduled run logs everything (the same structured JSON
# lines you'd see interactively) to data/logs/<product>.log, appended -
# nothing is shown on screen since Task Scheduler runs this unattended.

param(
    [string]$PulseRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$CredentialsScript = (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "local-mcp-server\set-credentials.local.ps1"),
    [string]$PythonExe = "python",
    [string]$Env = "production"
)

$Products = @("Groww", "INDMoney", "PowerUp Money", "Wealth Monitor", "Kuvera", "Porter")
$BaseTime = Get-Date -Hour 7 -Minute 0 -Second 0
$LogDir = Join-Path $PulseRoot "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (-not (Test-Path $CredentialsScript)) {
    Write-Error "Credentials script not found at $CredentialsScript - pass -CredentialsScript explicitly if it lives elsewhere."
    exit 1
}

for ($i = 0; $i -lt $Products.Count; $i++) {
    $product = $Products[$i]
    $slug = $product -replace ' ', ''
    $taskName = "PulseWeeklyRun-$slug"
    $fireTime = $BaseTime.AddMinutes($i * 15)
    $logPath = Join-Path $LogDir "$slug.log"

    $innerCommand = "& { . '$CredentialsScript'; Set-Location '$PulseRoot'; & '$PythonExe' -m pulse.cli --env $Env run --product '$product' *>> '$logPath' }"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"$innerCommand`""
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At $fireTime

    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Description "Weekly Review Pulse for $product (env=$Env)" -Force
    Write-Host "Registered $taskName firing Saturday $($fireTime.ToString('HH:mm')) local time -> logs to $logPath"
}

Write-Host "`nDone. Manual triggering still works independently, any time:"
Write-Host "  python -m pulse.cli --env $Env run --product `"<name>`""
Write-Host "`nVerify scheduled tasks with: Get-ScheduledTask -TaskName 'PulseWeeklyRun-*'"
Write-Host "Run one immediately (to test) with: Start-ScheduledTask -TaskName 'PulseWeeklyRun-Groww'"
Write-Host "Remove all with: Get-ScheduledTask -TaskName 'PulseWeeklyRun-*' | Unregister-ScheduledTask -Confirm:`$false"

# Registers one Windows Task Scheduler job per product, running
# `pulse run --product <name> --env production`.
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
# `run_pipeline`, so a manual run and any of the triggers below for the
# same (product, week) just make the later one(s) a no-op, whichever
# fires first - see orchestrator/run.py's in-flight guard and ledger check.
#
# Cadence (2026-08-31): each product fires up to THREE times a week -
# Monday 08:15, Wednesday 08:15, and Saturday 09:00 (local time; see the
# timezone note below) - but this is still ONE report per (product, ISO
# week), not three. The system's idempotency is keyed on (product,
# iso_week), and Monday/Wednesday/Saturday of the same calendar week all
# fall in that same ISO week, so whichever of the three fires FIRST and
# succeeds produces that week's report; the other two just find the week
# already SUCCEEDED and no-op (a cheap ledger lookup, no real ingestion/
# LLM/delivery work - see run_pipeline's early-return path). The point of
# three triggers is resilience (the machine being off/asleep on any one
# of the three days doesn't cost the week entirely), not three separate
# reports. If you ever want genuinely separate reports per trigger
# instead, that needs a real design change (idempotency keyed on run-date
# instead of ISO week, a new Doc-section-naming scheme, and dropping the
# ledger's current UNIQUE(product, iso_week) constraint) - deliberately
# not what this implements.
#
# EdgeCases/Phase6-Orchestration-Hardening.md #2: Windows Task Scheduler
# triggers are evaluated in the machine's LOCAL time zone, not IST. This
# script asks Task Scheduler for the times below in whatever time zone
# Windows itself is set to and does NOT convert from IST for you - if
# this machine isn't set to IST, either change the machine's time zone or
# adjust $TriggerSpecs below to the local-time equivalents yourself, and
# re-verify after any daylight-saving change. (Verified live 2026-08-30:
# this machine's timezone is already India Standard Time, so the times
# below are genuinely IST as written.)
#
# EdgeCases/Phase6-Orchestration-Hardening.md #9: all 6 products are
# staggered 15 minutes apart within each trigger day below (rather than
# firing simultaneously) - a real run takes 5-8 minutes end to end (real
# ingestion + embeddings + clustering are CPU-bound), so a short stagger
# would still overlap multiple heavy pipelines on one local machine if
# several of them need to do real work on the same day (e.g. every
# product's Monday attempt failed/was skipped, so Wednesday becomes the
# first real attempt for all 6 at once). Adjust if you add more products
# or move this to a beefier/cloud host.
#
# Each product's scheduled run logs everything (the same structured JSON
# lines you'd see interactively) to data/logs/<product>.log, appended -
# nothing is shown on screen since Task Scheduler runs this unattended.
#
# Power/battery (2026-08-31): tasks run regardless of AC power or battery
# state - $AllowStartIfOnBatteries/-DontStopIfGoingOnBatteries below.
#
# Logon (2026-08-31, explicit choice): tasks run as the ordinary
# "Interactive" logon type - they only fire while you're actually logged
# into Windows on this machine (locked screen is fine; signed all the way
# out, or a restart nobody's logged back into, is not). Pass
# -RunEvenWhenLoggedOff $true to switch to "run whether logged on or not"
# instead, which needs your Windows account password entered once,
# interactively (masked, via Read-Host -AsSecureString) - never accepted
# as a parameter value or logged, and only usable if you run this script
# yourself in your own terminal for that prompt to work.

param(
    [string]$PulseRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$CredentialsScript = (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "local-mcp-server\set-credentials.local.ps1"),
    [string]$PythonExe = "python",
    [string]$Env = "production",
    [bool]$RunEvenWhenLoggedOff = $false
)

$Products = @("Groww", "INDMoney", "PowerUp Money", "Wealth Monitor", "Kuvera", "Porter")

# (DaysOfWeek, base hour, base minute) - each product is offset from the
# base by (index * 15 minutes) within that day, same offsets reused across
# all three trigger days for consistency.
$TriggerSpecs = @(
    @{ Day = "Monday";    Hour = 8; Minute = 15 },
    @{ Day = "Wednesday"; Hour = 8; Minute = 15 },
    @{ Day = "Saturday";  Hour = 9; Minute = 0 }
)

$LogDir = Join-Path $PulseRoot "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (-not (Test-Path $CredentialsScript)) {
    Write-Error "Credentials script not found at $CredentialsScript - pass -CredentialsScript explicitly if it lives elsewhere."
    exit 1
}

$plainPassword = $null
if ($RunEvenWhenLoggedOff) {
    Write-Host "Enter your Windows account password for $env:USERDOMAIN\$env:USERNAME"
    Write-Host "(used once to register the tasks to run whether logged on or not; not stored or logged by this script)"
    $securePassword = Read-Host -AsSecureString -Prompt "Windows password"
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    $plainPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

$anyFailed = $false

for ($i = 0; $i -lt $Products.Count; $i++) {
    $product = $Products[$i]
    $slug = $product -replace ' ', ''
    $taskName = "PulseWeeklyRun-$slug"
    $logPath = Join-Path $LogDir "$slug.log"
    $offsetMinutes = $i * 15

    $triggers = foreach ($spec in $TriggerSpecs) {
        $fireTime = (Get-Date -Hour $spec.Hour -Minute $spec.Minute -Second 0).AddMinutes($offsetMinutes)
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek $spec.Day -At $fireTime
    }

    $innerCommand = "& { . '$CredentialsScript'; Set-Location '$PulseRoot'; & '$PythonExe' -m pulse.cli --env $Env run --product '$product' *>> '$logPath' }"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"$innerCommand`""
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

    try {
        if ($RunEvenWhenLoggedOff) {
            Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings `
                -Description "Weekly Review Pulse for $product (env=$Env)" `
                -User "$env:USERDOMAIN\$env:USERNAME" -Password $plainPassword -RunLevel Limited -Force -ErrorAction Stop | Out-Null
        } else {
            Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings `
                -Description "Weekly Review Pulse for $product (env=$Env)" -Force -ErrorAction Stop | Out-Null
        }
        $summary = ($TriggerSpecs | ForEach-Object {
            $t = (Get-Date -Hour $_.Hour -Minute $_.Minute -Second 0).AddMinutes($offsetMinutes)
            "$($_.Day) $($t.ToString('HH:mm'))"
        }) -join ", "
        Write-Host "Registered $taskName firing $summary local time -> logs to $logPath"
    } catch {
        $anyFailed = $true
        Write-Host "FAILED to register $taskName : $($_.Exception.Message)" -ForegroundColor Red
    }
}

if ($plainPassword) {
    $plainPassword = $null
    [System.GC]::Collect()
}

if ($anyFailed) {
    Write-Host "`nOne or more tasks FAILED to register - see above. Existing tasks of the same name are left untouched if registration failed (Register-ScheduledTask validates before replacing)." -ForegroundColor Yellow
}

Write-Host "`nDone. Manual triggering still works independently, any time:"
Write-Host "  python -m pulse.cli --env $Env run --product `"<name>`""
Write-Host "`nVerify scheduled tasks with: Get-ScheduledTask -TaskName 'PulseWeeklyRun-*'"
Write-Host "Run one immediately (to test) with: Start-ScheduledTask -TaskName 'PulseWeeklyRun-Groww'"
Write-Host "Pause all (keep config, stop firing) with:"
Write-Host "  Get-ScheduledTask -TaskName 'PulseWeeklyRun-*' | Disable-ScheduledTask"
Write-Host "Resume with:"
Write-Host "  Get-ScheduledTask -TaskName 'PulseWeeklyRun-*' | Enable-ScheduledTask"
Write-Host "Remove permanently with:"
Write-Host "  Get-ScheduledTask -TaskName 'PulseWeeklyRun-*' | Unregister-ScheduledTask -Confirm:`$false"

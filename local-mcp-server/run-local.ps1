# One-time interactive login + local run of google_workspace_mcp.
# Run this from a PowerShell terminal (not via the agent) after filling in
# set-credentials.local.ps1 with your real Client ID/Secret.

$env:Path = "C:\Users\HP\.local\bin;$env:Path"

$localCreds = Join-Path $PSScriptRoot "set-credentials.local.ps1"
if (-not (Test-Path $localCreds)) {
    Write-Host "Missing set-credentials.local.ps1 - copy set-credentials.example.ps1 to that name and fill in your real Client ID/Secret first." -ForegroundColor Red
    exit 1
}

. $localCreds

uvx workspace-mcp --single-user --tool-tier core

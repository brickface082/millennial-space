# Send a task to OpenClaw (Az) on the millennial-space-growth session.
# Usage:
#   .\send-to-openclaw.ps1 -Message "Execute step 2.1 from GROWTH-PLAN.md"
#   .\send-to-openclaw.ps1 -File "C:\path\to\brief.md"
#   Get-Content ACTIVE.md -Raw | .\send-to-openclaw.ps1

param(
    [string]$Message = "",
    [string]$File = "",
    [string]$SessionKey = "millennial-space-growth",
    [string]$Agent = "main",
    [int]$TimeoutSec = 900
)

$ErrorActionPreference = "Stop"
$MarketingDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StatusFile = Join-Path $MarketingDir "STATUS.md"

if ($File -and (Test-Path $File)) {
    $Message = Get-Content $File -Raw -Encoding UTF8
}
if (-not $Message.Trim()) {
    Write-Error "Provide -Message or -File"
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"`n## OpenClaw dispatch $stamp`n**Session:** $SessionKey`n**Prompt preview:** $($Message.Substring(0, [Math]::Min(200, $Message.Length)))...`n" | Add-Content $StatusFile -Encoding UTF8

Write-Host "Sending to OpenClaw agent '$Agent' (session: $SessionKey)..." -ForegroundColor Cyan

$outFile = Join-Path $env:TEMP "openclaw-growth-$(Get-Date -Format 'yyyyMMdd-HHmmss').txt"
openclaw agent --agent $Agent --session-key $SessionKey --message $Message --timeout $TimeoutSec 2>&1 | Tee-Object -FilePath $outFile

"`n### Response ($stamp)`n``````n$(Get-Content $outFile -Raw)`n``````n" | Add-Content $StatusFile -Encoding UTF8
Write-Host "Logged to $StatusFile" -ForegroundColor Green
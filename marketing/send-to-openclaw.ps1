# Send a task to OpenClaw (Az) on the millennial-space-growth session.
# Usage:
#   .\send-to-openclaw.ps1 -Message "Execute step 2.1 from GROWTH-PLAN.md"
#   .\send-to-openclaw.ps1 -File "C:\path\to\brief.md"

param(
    [string]$Message = "",
    [string]$File = "",
    [string]$SessionKey = "millennial-space-growth",
    [string]$Agent = "main",
    [int]$TimeoutSec = 900
)

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
$msgFile = Join-Path $env:TEMP "openclaw-growth-msg-$(Get-Date -Format 'yyyyMMdd-HHmmss').txt"
Set-Content -Path $msgFile -Value $Message -Encoding UTF8

$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    # Plugin warnings go to stderr — must not terminate the script.
    $output = & openclaw agent --agent $Agent --session-key $SessionKey --message $Message --timeout $TimeoutSec 2>&1
    $exitCode = $LASTEXITCODE
    $output | Out-File -FilePath $outFile -Encoding UTF8
} finally {
    $ErrorActionPreference = $prevEap
}

$response = ""
if (Test-Path $outFile) {
    $response = Get-Content $outFile -Raw -ErrorAction SilentlyContinue
}

"`n### Response ($stamp) exit=$exitCode`n``````n$response`n``````n" | Add-Content $StatusFile -Encoding UTF8

if ($exitCode -ne 0) {
    Write-Host "OpenClaw exited with code $exitCode (see $StatusFile)" -ForegroundColor Yellow
    exit $exitCode
}

Write-Host "Logged to $StatusFile" -ForegroundColor Green
# Pop an on-screen alert when OpenClaw needs Chris to click CAPTCHA / verify.
param(
    [string]$Title = "OpenClaw needs you",
    [string]$Message = "Check marketing\NEEDS-CHRIS.md — captcha or click required for outreach.",
    [string]$Url = ""
)

Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.MessageBox]::Show(
    $Message,
    $Title,
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Information
) | Out-Null

if ($Url) {
    Start-Process $Url
} elseif (Test-Path "$PSScriptRoot\..\NEEDS-CHRIS.md") {
    Start-Process notepad.exe "$PSScriptRoot\..\NEEDS-CHRIS.md"
}
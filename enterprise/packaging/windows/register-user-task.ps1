# Active Setup stub: first logon per user. Expands the task XML and
# registers a LIMITED InteractiveToken task named SwitchBay.
# MSI must NOT create this task as SYSTEM.
param(
    [string]$InstallDir = $(if ($env:SWITCHBAY_INSTALL_ROOT) { $env:SWITCHBAY_INSTALL_ROOT } else { "${env:ProgramFiles}\SwitchBay" })
)

$ErrorActionPreference = "Stop"
$ws = Join-Path $env:USERPROFILE "SwitchBay\workspace"
New-Item -ItemType Directory -Force -Path $ws | Out-Null
$local = Join-Path $env:LOCALAPPDATA "switchbay"
New-Item -ItemType Directory -Force -Path (Join-Path $local "logs") | Out-Null

$hostExe = Join-Path $InstallDir "bin\switchbay.exe"
if (-not (Test-Path $hostExe)) {
    $hostExe = Join-Path $InstallDir "python\cpython-*\python.exe"
    $hostExe = (Get-Item $hostExe -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
}
$tmpl = Join-Path $InstallDir "enterprise\packaging\windows\SwitchBay.xml.template"
$xml = Get-Content -Raw -Path $tmpl
$xml = $xml.Replace("{{USERID}}", [System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$xml = $xml.Replace("{{HOST}}", $hostExe)
$xml = $xml.Replace("{{WORKSPACE}}", $ws)
$xml = $xml.Replace("{{INSTALLDIR}}", $InstallDir)
$out = Join-Path $local "SwitchBay.xml"
Set-Content -Path $out -Value $xml -Encoding Unicode

schtasks /Create /TN "SwitchBay" /XML $out /F | Out-Null
schtasks /Run /TN "SwitchBay" | Out-Null

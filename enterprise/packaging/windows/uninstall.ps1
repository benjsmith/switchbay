# Intune Win32 uninstall (SYSTEM). Leaves user data
# (%LOCALAPPDATA%\switchbay and %USERPROFILE%\SwitchBay).
param(
    [string]$Dest = $(Join-Path ${env:ProgramFiles} "SwitchBay")
)
$ErrorActionPreference = "SilentlyContinue"
schtasks /Delete /TN "SwitchBay" /F | Out-Null
$guid = "{A7B5D2C8-9C31-4A6E-1F7D-9E4C8B2A0001}"
Remove-Item -Path "HKLM:\SOFTWARE\Microsoft\Active Setup\Installed Components\$guid" -Recurse -Force
if (Test-Path $Dest) {
    Remove-Item -Path $Dest -Recurse -Force
}

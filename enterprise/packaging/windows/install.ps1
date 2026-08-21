# Intune Win32 install (SYSTEM). Copies the bake layout to Program Files
# and registers Active Setup so the *user* task is created at first logon.
# Do not run uv, pnpm, or python -m switchbay service install.
param(
    [string]$Layout = $(Join-Path $PSScriptRoot "layout"),
    [string]$Dest = $(Join-Path ${env:ProgramFiles} "SwitchBay")
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path (Join-Path $Layout "src"))) {
    throw "layout missing src\ — run scripts/bake_enterprise.py first (Layout=$Layout)"
}
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
Copy-Item -Path (Join-Path $Layout "*") -Destination $Dest -Recurse -Force

$overlaySrc = Join-Path $PSScriptRoot "admin.overlay.json"
$overlayDstDir = Join-Path ${env:ProgramData} "SwitchBay"
if (Test-Path $overlaySrc) {
    New-Item -ItemType Directory -Force -Path $overlayDstDir | Out-Null
    Copy-Item $overlaySrc (Join-Path $overlayDstDir "admin.json") -Force
}

$guid = "{A7B5D2C8-9C31-4A6E-1F7D-9E4C8B2A0001}"
$reg = "HKLM:\SOFTWARE\Microsoft\Active Setup\Installed Components\$guid"
New-Item -Path $reg -Force | Out-Null
$stub = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Dest\enterprise\packaging\windows\register-user-task.ps1`" -InstallDir `"$Dest`""
New-ItemProperty -Path $reg -Name "StubPath" -Value $stub -PropertyType String -Force | Out-Null
# Bump this on each fleet MSI/Win32 that must re-run first-logon for existing users.
New-ItemProperty -Path $reg -Name "Version" -Value "1,0,1,0" -PropertyType String -Force | Out-Null
New-ItemProperty -Path $reg -Name "Locale" -Value "*" -PropertyType String -Force | Out-Null

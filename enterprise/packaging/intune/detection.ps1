$root = Join-Path ${env:ProgramFiles} "SwitchBay"
$exe = Join-Path $root "bin\switchbay.exe"
if (-not (Test-Path $exe)) {
    $exe = Join-Path $root "bin\python.exe"
}
if (-not (Test-Path $exe)) { exit 1 }
if (Test-Path (Join-Path $root "src\switchbay\__init__.py")) { exit 0 }
$v = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($exe).FileVersion
if ($v -and [version]$v -ge [version]"0.9.18") { exit 0 }
exit 1

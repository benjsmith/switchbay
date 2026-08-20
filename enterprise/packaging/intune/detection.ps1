$exe = Join-Path ${env:ProgramFiles} "SwitchBay\bin\switchbay.exe"
if (-not (Test-Path $exe)) { exit 1 }
$v = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($exe).FileVersion
if ([version]$v -ge [version]"0.9.16") { exit 0 }
exit 1

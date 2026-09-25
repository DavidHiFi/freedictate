# FreeDictate bootstrap installer.
# Downloads the release, extracts it to %LOCALAPPDATA%\FreeDictate, then runs the real installer.
#
# Run it in PowerShell:
#   irm https://github.com/DavidHiFi/freedictate/releases/latest/download/Install.ps1 | iex
#
# It changes two things and nothing else:
#   1. Puts FreeDictate files in %LOCALAPPDATA%\FreeDictate
#   2. Runs Install-FreeDictate.ps1 -Install, which adds pip packages and ONE Run key for autostart
# It never touches mic routing, audio apps, drivers, display settings, or services.

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$RepoUrl  = "https://github.com/DavidHiFi/freedictate/releases/latest/download/freedictate.zip"
$Dest     = Join-Path $env:LOCALAPPDATA "FreeDictate"
$Stage    = Join-Path $env:TEMP ("freedictate-stage-" + [guid]::NewGuid().ToString("N"))
$Zip      = Join-Path $env:TEMP "freedictate-release.zip"

Write-Output "FreeDictate installer"
Write-Output "  Install folder: $Dest"

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) {
  Write-Output ""
  Write-Output "Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/"
  Write-Output "and tick 'Add python.exe to PATH' during setup. Nothing was installed."
  return
}
Write-Output "  Python: $py"
& $py --version 2>&1 | Write-Output
Write-Output ""

Write-Output "Downloading $RepoUrl"
Invoke-WebRequest -Uri $RepoUrl -OutFile $Zip -UseBasicParsing

New-Item -ItemType Directory -Path $Stage -Force | Out-Null
Expand-Archive -Path $Zip -DestinationPath $Stage -Force

# The zip holds the project files at its root. Move them into place without
# deleting anything already there, so an upgrade keeps transcripts.log.
New-Item -ItemType Directory -Path $Dest -Force | Out-Null
Get-ChildItem -LiteralPath $Stage | ForEach-Object {
  Copy-Item -LiteralPath $_.FullName -Destination $Dest -Recurse -Force
}
Remove-Item -LiteralPath $Stage -Recurse -Force
Remove-Item -LiteralPath $Zip -Force

Write-Output "Files in $Dest"
Write-Output ""

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Dest "Install-FreeDictate.ps1") -Install
$rc = $LASTEXITCODE

Write-Output ""
if ($rc -eq 0) {
  Write-Output "Done. Start it from Start-FreeDictate.cmd, or log in again and it starts on its own."
  Write-Output "Hold Ctrl+Win, speak, release. Text pastes at the cursor."
} else {
  Write-Output "Installer exited with code $rc. Nothing was removed. Re-run this script to retry."
}
return

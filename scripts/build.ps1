<#
  FreeDictate one-command build.

    pwsh -File scripts\build.ps1                     exe + self-test + installer + portable zip
    pwsh -File scripts\build.ps1 -SkipTests          skip pytest
    pwsh -File scripts\build.ps1 -SkipPyInstaller    reuse dist\ from a previous build
    pwsh -File scripts\build.ps1 -SkipInstaller      exe + portable only
    pwsh -File scripts\build.ps1 -Python <path>      use a specific interpreter
                                                     (default: "python" on PATH)

  Requires Python 3.11+ with requirements.txt installed (including PyInstaller),
  and Inno Setup 6.5+ on disk for the installer step. The self-test step needs a
  desktop session; pass -NoSelfTest to skip it (headless machines).

  Outputs in dist\:
    FreeDictate\                          the frozen app folder
    FreeDictate-<version>-Setup.exe       Inno Setup installer
    FreeDictate-<version>-Portable.zip    portable build (portable.txt marker inside)
#>
[CmdletBinding()]
param(
  [switch]$SkipTests,
  [switch]$SkipInstaller,
  [switch]$SkipPyInstaller,
  [switch]$NoSelfTest,
  [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Native {
  & $args[0] $args[1..($args.Count - 1)]
  if ($LASTEXITCODE -ne 0) { throw "$($args[0]) exited with $LASTEXITCODE" }
}

# --- version ----------------------------------------------------------------
$initSrc = Get-Content "$Root\src\freedictate\__init__.py" -Raw
$Version = [regex]::Match($initSrc, '__version__ = "([^"]+)"').Groups[1].Value
if (-not $Version) { throw "Could not read __version__ from src\freedictate\__init__.py" }
Write-Host "== FreeDictate $Version =="

$major, $minor, $patch = 0, 0, 0
if ($Version -match "^(\d+)\.(\d+)\.(\d+)") {
  $major = [int]$Matches[1]; $minor = [int]$Matches[2]; $patch = [int]$Matches[3]
}

# Regenerate the version resource so the exe metadata always matches the code.
@((Get-Content "$Root\packaging\version_info.txt" -Raw)) | Out-Null  # existence check
$vi = Get-Content "$Root\packaging\version_info.txt" -Raw
$vi = $vi -replace "filevers=\([\d, ]+\)", "filevers=($major, $minor, $patch, 0)"
$vi = $vi -replace "prodvers=\([\d, ]+\)", "prodvers=($major, $minor, $patch, 0)"
$vi = $vi -replace 'StringStruct\("FileVersion", "[^"]+"\)', "StringStruct(`"FileVersion`", `"$Version`")"
$vi = $vi -replace 'StringStruct\("ProductVersion", "[^"]+"\)', "StringStruct(`"ProductVersion`", `"$Version`")"
Set-Content "$Root\packaging\version_info.txt" $vi -Encoding UTF8

# --- icon -------------------------------------------------------------------
if (-not (Test-Path "$Root\assets\freedictate.ico")) {
  Write-Host "== generating assets\freedictate.ico =="
  $code = "import sys; sys.path.insert(0, r'$Root\src'); from freedictate.__main__ import main; sys.exit(main(['--make-icon', r'$Root\assets\freedictate.ico']))"
  Invoke-Native $Python -c $code
}

# --- tests ------------------------------------------------------------------
if (-not $SkipTests) {
  Write-Host "== tests =="
  $env:FREEDICTATE_HOME = Join-Path $env:TEMP "freedictate-build-tests"
  # Own scratch root, so a stale or locked %TEMP%\pytest-of-* dir can't break the build.
  Invoke-Native $Python -m pytest tests -q "--basetemp=$(Join-Path $env:TEMP 'freedictate-build-pytest')"
}

# --- frozen build -----------------------------------------------------------
$exe = "$Root\dist\FreeDictate\FreeDictate.exe"
if (-not $SkipPyInstaller) {
  Write-Host "== pyinstaller =="
  Invoke-Native $Python -m PyInstaller packaging\freedictate.spec --noconfirm
}

# --- self-test --------------------------------------------------------------
if (-not (Test-Path $exe)) { throw "PyInstaller did not produce $exe" }
if (-not $NoSelfTest) {
  Write-Host "== self-test on the frozen exe =="
  $report = Join-Path $env:TEMP "freedictate-selftest.txt"
  if (Test-Path $report) { Remove-Item $report -Force }
  $p = Start-Process -FilePath $exe -ArgumentList "--self-test", $report -Wait -PassThru
  Get-Content $report
  if ($p.ExitCode -ne 0) { throw "Self-test FAILED (exit $($p.ExitCode))" }
}

# --- installer --------------------------------------------------------------
if (-not $SkipInstaller) {
  Write-Host "== inno setup =="
  $iscc = @(
    "C:\Program Files (x86)\Inno Setup 7\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
  ) | Where-Object { Test-Path $_ } | Select-Object -First 1
  if (-not $iscc) { $iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source }
  if (-not $iscc) { throw "Inno Setup not found. Install it or run with -SkipInstaller." }
  Invoke-Native $iscc "/DAppVersion=$Version" "/DSourceDir=$Root\dist\FreeDictate" "/DOutputDir=$Root\dist" "$Root\packaging\installer.iss"
}

# --- portable zip -----------------------------------------------------------
Write-Host "== portable zip =="
$stage = Join-Path $env:TEMP "freedictate-portable-stage"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path "$stage\FreeDictate" | Out-Null
Copy-Item "$Root\dist\FreeDictate\*" "$stage\FreeDictate" -Recurse -Force
Set-Content "$stage\FreeDictate\portable.txt" "" -Encoding ASCII
@(
  "FreeDictate $Version - portable",
  "",
  "Run FreeDictate.exe. The portable.txt marker in this folder tells FreeDictate",
  "to keep everything - settings, history and downloaded models - in data\ next",
  "to the exe, so the whole folder can live on a USB stick or any folder you like",
  "and move with you. Nothing is written to the registry or AppData.",
  "",
  "First run: pick a voice model in Settings; it downloads once (needs internet)",
  "and then all dictation stays offline.",
  "",
  "To update by hand: download the newest portable zip, extract it over this",
  "folder, and keep your data\ folder. FreeDictate can also update itself from",
  "its Settings window.",
  "",
  "https://github.com/DavidHiFi/freedictate"
) | Set-Content "$stage\FreeDictate\PORTABLE-README.txt" -Encoding UTF8
$zip = "$Root\dist\FreeDictate-$Version-Portable.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path "$stage\FreeDictate" -DestinationPath $zip -CompressionLevel Optimal
Remove-Item $stage -Recurse -Force

# --- receipt ----------------------------------------------------------------
Write-Host "== artifacts =="
Get-ChildItem "$Root\dist" -File | ForEach-Object {
  "{0,12:N0}  {1}  {2}" -f $_.Length, (Get-FileHash $_.FullName -Algorithm SHA256).Hash.Substring(0, 16), $_.Name
}
# Attach this file to the release: the in-app updater verifies its download
# against a SHA256SUMS asset when one is present (updater._expected_sha).
Get-ChildItem "$Root\dist" -File -Filter "FreeDictate-$Version-*" | ForEach-Object {
  "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name
} | Set-Content "$Root\dist\SHA256SUMS" -Encoding ASCII
Write-Host "== build complete =="

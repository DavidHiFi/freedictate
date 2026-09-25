# FreeDictate installer. One controlled change at a time. Backs up before writing.
# Audit mode changes nothing. Install only adds ONE Run key for autostart.
param(
  [switch]$Audit,
  [switch]$Install,
  [switch]$Uninstall,
  [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$RunName = "FreeDictate"
$BackupDir = Join-Path $Dir "backups"

function Show-Audit {
  Write-Output "FreeDictate audit. Read only, changes nothing."
  Write-Output "Dir: $Dir"
  $py = if ($PythonExe) { $PythonExe } else { (Get-Command python -ErrorAction SilentlyContinue).Source }
  Write-Output "Python: $py"
  if ($py) { & $py --version 2>&1 | Write-Output }
  Write-Output ""
  Write-Output "Required files:"
  foreach ($f in @("freedictate.py","config.json","requirements.txt")) {
    $p = Join-Path $Dir $f
    Write-Output "  $f : $(if (Test-Path -LiteralPath $p) { 'present' } else { 'MISSING' })"
  }
  Write-Output ""
  Write-Output "Python packages:"
  if ($py) { & $py -m pip show faster-whisper sounddevice numpy pyperclip pynput 2>&1 | Select-String "Name|Version|not found" | Write-Output }
  Write-Output ""
  Write-Output "Startup Run key:"
  $v = Get-ItemProperty -LiteralPath $RunPath -Name $RunName -ErrorAction SilentlyContinue
  if ($null -eq $v) { Write-Output "  Not installed. No autostart entry." }
  else { Write-Output "  Present: $($v.$RunName)" }
  Write-Output ""
  Write-Output "Protected apps: this script never touches audio routing, comms apps, or drivers."
  Write-Output "Result: audit done. No settings changed."
}

if ($Audit -or (-not $Install -and -not $Uninstall)) {
  Show-Audit
  exit 0
}

if ($Uninstall) {
  $existing = Get-ItemProperty -LiteralPath $RunPath -Name $RunName -ErrorAction SilentlyContinue
  if ($null -ne $existing) {
    if (-not (Test-Path -LiteralPath $BackupDir)) { New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null }
    $bak = Join-Path $BackupDir "freedictate-run-before-remove.reg"
    reg export "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" $bak /y | Out-Null
    Write-Output "Backup: $bak"
    Remove-ItemProperty -LiteralPath $RunPath -Name $RunName
    Write-Output "Removed autostart entry $RunName. Wispr Flow untouched. No restart needed."
  } else {
    Write-Output "No autostart entry found. Nothing changed."
  }
  exit 0
}

if ($Install) {
  $py = if ($PythonExe) { $PythonExe } else { (Get-Command python -ErrorAction SilentlyContinue).Source }
  if (-not $py) { throw "Python not found. Install Python 3.10+ first. Nothing changed." }
  Write-Output "Installing packages (user site, no system change)..."
  & $py -m pip install -r (Join-Path $Dir "requirements.txt")
  Write-Output ""
  Write-Output "Preloading whisper model (downloads once, about 500 MB for small.en)..."
  & $py (Join-Path $Dir "freedictate.py") --preload
  Write-Output ""
  & $py (Join-Path $Dir "freedictate.py") --audit
  if (-not (Test-Path -LiteralPath $BackupDir)) { New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null }
  $bak = Join-Path $BackupDir "freedictate-run-before-install.reg"
  reg export "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" $bak /y | Out-Null
  Write-Output "Backup: $bak"
  $cmd = "`"$py`" `"$Dir\freedictate.py`""
  $pyw = $py -replace "python\.exe$", "pythonw.exe"
  if (Test-Path -LiteralPath $pyw) { $cmd = "`"$pyw`" `"$Dir\freedictate.py`"" }
  New-ItemProperty -LiteralPath $RunPath -Name $RunName -Value $cmd -PropertyType String -Force | Out-Null
  Write-Output "Added autostart: $RunName = $cmd"
  Write-Output "Changed: pip packages + ONE Run key. Unchanged: mic routing, audio apps, display settings."
  Write-Output "Rollback: run with -Uninstall, or merge $bak. No restart needed."
  exit 0
}

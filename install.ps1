<#
MetaDashboard installer: profit calendar for several MT5 accounts (Windows).

    powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/yohannaftali/MetaDashboard/main/install.ps1 | iex"

Installs uv if it is missing, installs MetaDashboard as a uv tool (its own Python and packages, nothing
system-wide) and adds Start menu and desktop shortcuts. Run it again to update. Settings and data stay in
%LOCALAPPDATA%\MetaDashboard. To uninstall:

    powershell -ExecutionPolicy ByPass -c "& ([scriptblock]::Create((irm https://raw.githubusercontent.com/yohannaftali/MetaDashboard/main/install.ps1))) -Uninstall"
#>
param(
    [switch]$Uninstall,
    # what to install: the GitHub archive of main (no git needed), or a local folder / other URL
    [string]$Source = 'https://github.com/yohannaftali/MetaDashboard/archive/refs/heads/main.zip',
    [switch]$NoShortcuts
)

$ErrorActionPreference = 'Stop'
$AppName = 'MetaDashboard'
$Package = 'metadashboard'
$DataDir = Join-Path $env:LOCALAPPDATA $AppName
$Shortcuts = @(
    (Join-Path ([Environment]::GetFolderPath('Programs')) "$AppName.lnk"),
    (Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppName.lnk")
)

function Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }

function Get-Uv {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) { return $uv.Source }
    $local = Join-Path $env:USERPROFILE '.local\bin\uv.exe'  # where the uv installer puts it
    if (Test-Path $local) { return $local }
    return $null
}

if ($env:OS -ne 'Windows_NT') { throw "$AppName runs on Windows only (the MetaTrader5 package is Windows-only)." }

if ($Uninstall) {
    $uv = Get-Uv
    if ($uv) {
        Step "Removing $AppName"
        & $uv tool uninstall $Package
    }
    $Shortcuts | Where-Object { Test-Path $_ } | ForEach-Object { Remove-Item $_ }
    Write-Host ""
    Write-Host "$AppName removed. Your settings and data were kept in $DataDir"
    Write-Host "(accounts with encrypted investor passwords, fetched history). Delete that folder to remove them too."
    return
}

$uv = Get-Uv
if (-not $uv) {
    Step 'Installing uv (https://docs.astral.sh/uv/)'
    # in a child PowerShell, so the uv installer cannot change or end this session
    powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    $uv = Get-Uv
    if (-not $uv) { throw 'uv was not found after installing it. Open a new PowerShell window and run this installer again.' }
}
Step "Using uv: $uv"

Step "Installing $AppName from $Source"
# --reinstall-package fetches the source again, so running the installer again updates the app
& $uv tool install --force --reinstall-package $Package $Source
if ($LASTEXITCODE -ne 0) { throw "uv tool install failed (exit code $LASTEXITCODE)." }

$bin = (& $uv tool dir --bin).Trim()
$exe = Join-Path $bin "$Package-gui.exe"
if (-not (Test-Path $exe)) { throw "Installed, but $exe is missing." }

if (-not $NoShortcuts) {
    Step 'Adding Start menu and desktop shortcuts'
    New-Item -ItemType Directory -Force $DataDir | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    foreach ($path in $Shortcuts) {
        $lnk = $shell.CreateShortcut($path)
        $lnk.TargetPath = $exe
        $lnk.WorkingDirectory = $DataDir
        $lnk.Description = 'Profit calendar for several MT5 accounts'
        $lnk.Save()
    }
}

Write-Host ""
Write-Host "$AppName installed." -ForegroundColor Green
Write-Host "  Start it from the Start menu or desktop shortcut, or run:  $Package"
Write-Host "  Try it without MT5:                                        $Package --demo"
Write-Host "  Settings and data:                                         $DataDir"
Write-Host ""
Write-Host "Before the first Refresh, set up a terminal used ONLY for monitoring (logging in switches that"
Write-Host "terminal's account, so never use the terminal that runs your EAs):"
Write-Host "  1. Copy 'C:\Program Files\MetaTrader 5' to e.g. C:\MT5-Monitor"
Write-Host "  2. Run C:\MT5-Monitor\terminal64.exe /portable once and add each broker (File > Open an Account)"
Write-Host "  3. In $AppName > Settings, enter C:\MT5-Monitor\terminal64.exe and your accounts (investor passwords)"
Write-Host "The first start downloads the Flet window client once and can take a minute."

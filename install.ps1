# KAMP-K2 one-shot PowerShell installer.
#
# For non-technical users — downloads the repo, checks Python + paramiko,
# prompts for printer IP, detects existing install, runs installer/revert.
# No manual SSH needed.
#
# Run from PowerShell (not cmd.exe):
#
#   iwr -useb https://raw.githubusercontent.com/grant0013/KAMP-K2/main/install.ps1 | iex
#
# Or download this file and run: .\install.ps1
#
# Optional parameters:
#   .\install.ps1 -Host 192.168.1.42
#   .\install.ps1 -Host 192.168.1.42 -Password mypass
#   .\install.ps1 -Revert              # revert without menu

[CmdletBinding()]
param(
    [string]$PrinterHost = "",
    [string]$Password = "creality_2024",
    [ValidateSet("auto", "F008", "F021")]
    [string]$Board = "auto",
    [switch]$Revert,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$InstallDir   = Join-Path $env:USERPROFILE "KAMP-K2"
$BackupDir    = Join-Path $env:USERPROFILE "KAMP-K2\backups"
$RepoZipUrl   = "https://github.com/grant0013/KAMP-K2/archive/refs/heads/main.zip"

function Write-Step($msg) { Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "[+] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "[x] $msg" -ForegroundColor Red }

function Test-Python {
    foreach ($cmd in @("python", "py")) {
        try {
            $out = & $cmd --version 2>&1
            if ($out -match "Python\s+3\.") { return $cmd }
        } catch { continue }
    }
    return $null
}

function Ensure-Python {
    $py = Test-Python
    if ($py) {
        Write-Ok "Python found: $py ($(& $py --version 2>&1))"
        return $py
    }
    Write-Err "Python 3 not found on PATH."
    Write-Host ""
    Write-Host "Install Python 3 from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "IMPORTANT: tick 'Add Python to PATH' during install." -ForegroundColor Yellow
    Write-Host ""
    $open = Read-Host "Open the Python download page now? [Y/n]"
    if ($open -ne "n") {
        Start-Process "https://www.python.org/downloads/"
    }
    exit 1
}

function Ensure-Paramiko($py) {
    Write-Step "Checking paramiko..."
    $check = & $py -c "import paramiko; print(paramiko.__version__)" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "paramiko present (version $check)"
        return
    }
    Write-Step "Installing paramiko (pip install --user)..."
    & $py -m pip install --user --quiet paramiko
    if ($LASTEXITCODE -ne 0) {
        Write-Err "pip install paramiko failed. Try manually:"
        Write-Err "  $py -m pip install paramiko"
        exit 1
    }
    Write-Ok "paramiko installed"
}

function Download-Repo {
    Write-Step "Downloading KAMP-K2 from GitHub..."
    $tmpZip = Join-Path $env:TEMP "KAMP-K2-main.zip"
    Invoke-WebRequest -Uri $RepoZipUrl -OutFile $tmpZip -UseBasicParsing

    if (Test-Path $InstallDir) {
        Write-Step "Removing previous install at $InstallDir..."
        # Preserve the backups directory across repo re-downloads.
        $preservedBackups = $null
        if (Test-Path $BackupDir) {
            $preservedBackups = Join-Path $env:TEMP "KAMP-K2-backups-preserve"
            if (Test-Path $preservedBackups) {
                Remove-Item -Recurse -Force $preservedBackups
            }
            Move-Item $BackupDir $preservedBackups
        }
        Remove-Item -Recurse -Force $InstallDir
        if ($preservedBackups) {
            New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
            Move-Item (Join-Path $preservedBackups "*") $BackupDir
            Remove-Item -Recurse -Force $preservedBackups
        }
    }
    Write-Step "Extracting to $InstallDir..."
    $tmpExtract = Join-Path $env:TEMP "KAMP-K2-extract"
    if (Test-Path $tmpExtract) { Remove-Item -Recurse -Force $tmpExtract }
    Expand-Archive -Path $tmpZip -DestinationPath $tmpExtract
    $inner = Get-ChildItem -Path $tmpExtract | Where-Object { $_.PSIsContainer } | Select-Object -First 1
    Move-Item $inner.FullName $InstallDir
    Remove-Item -Recurse -Force $tmpExtract, $tmpZip
    Write-Ok "Repo ready at $InstallDir"
}

function Get-PrinterHost {
    if ($PrinterHost) { return $PrinterHost }
    Write-Host ""
    Write-Host "Find your printer's IP on the touchscreen:" -ForegroundColor Yellow
    Write-Host "  Settings -> Network -> IP Address (e.g. 192.168.1.170)" -ForegroundColor Yellow
    Write-Host ""
    do {
        $ip = Read-Host "Enter your printer's IP address"
        $ip = $ip.Trim()
    } while (-not ($ip -match "^\d{1,3}(\.\d{1,3}){3}$"))
    return $ip
}

function Run-Installer($py, [string[]]$extraArgs) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    $args = @("install_k2.py",
              "--host", $ip,
              "--password", $Password,
              "--board", $Board,
              "--local-backup-dir", $BackupDir)
    $args += $extraArgs
    if ($DryRun) { $args += "--dry-run" }

    Push-Location $InstallDir
    try {
        & $py @args
        return $LASTEXITCODE
    } finally {
        Pop-Location
    }
}

function Detect-Install($py) {
    Write-Step "Checking printer state at $ip..."
    $detectArgs = @("install_k2.py",
                    "--host", $ip,
                    "--password", $Password,
                    "--detect")
    Push-Location $InstallDir
    try {
        $out = & $py @detectArgs 2>&1 | Out-String
    } finally {
        Pop-Location
    }
    $status = ($out -split "`n" | Where-Object { $_ -match "KAMPK2_STATUS=" } | Select-Object -First 1)
    $board  = ($out -split "`n" | Where-Object { $_ -match "KAMPK2_BOARD=" }  | Select-Object -First 1)
    if ($status -match "KAMPK2_STATUS=(\w+)") { $s = $Matches[1] } else { $s = "unknown" }
    if ($board  -match "KAMPK2_BOARD=(\w+)")  { $b = $Matches[1] } else { $b = "unknown" }
    return @{ Status = $s; Board = $b; RawOutput = $out }
}

function Show-Menu($detected) {
    Write-Host ""
    Write-Host "================================================" -ForegroundColor Cyan
    Write-Host " KAMP-K2 is already installed on this printer." -ForegroundColor Cyan
    Write-Host " Board detected: $($detected.Board)" -ForegroundColor Cyan
    Write-Host "================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  [1] Update / reinstall (pulls latest from GitHub)"
    Write-Host "  [2] Revert (restore original Creality configs, remove KAMP-K2)"
    Write-Host "  [3] Exit without changes"
    Write-Host ""
    do {
        $choice = Read-Host "Choose [1-3]"
    } while ($choice -notin @("1", "2", "3"))
    return $choice
}

# --- main -------------------------------------------------------------------

Write-Host ""
Write-Host "================================" -ForegroundColor Cyan
Write-Host " KAMP-K2 PowerShell installer"   -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

$py = Ensure-Python
Ensure-Paramiko $py
Download-Repo

$ip = Get-PrinterHost

# Short-circuit: explicit -Revert flag skips the menu.
if ($Revert) {
    Write-Step "Running revert against $ip..."
    $rc = Run-Installer $py @("--revert")
    exit $rc
}

# Detect existing install and branch.
$detected = Detect-Install $py
if ($detected.Status -eq "installed") {
    $choice = Show-Menu $detected
    switch ($choice) {
        "1" {
            Write-Step "Running update/reinstall against $ip..."
            $rc = Run-Installer $py @()
        }
        "2" {
            Write-Step "Running revert against $ip..."
            $rc = Run-Installer $py @("--revert")
        }
        "3" {
            Write-Ok "Exited without changes."
            exit 0
        }
    }
} elseif ($detected.Status -eq "fresh") {
    Write-Ok "No existing install detected. Proceeding with fresh install."
    Write-Step "Running installer against $ip (board=$($detected.Board))..."
    $rc = Run-Installer $py @()
} else {
    Write-Warn "Could not determine install state. Detect output:"
    Write-Host $detected.RawOutput
    $go = Read-Host "Proceed with install anyway? [y/N]"
    if ($go -ne "y") { exit 1 }
    $rc = Run-Installer $py @()
}

Write-Host ""
if ($rc -eq 0) {
    Write-Ok "Done!"
    Write-Host ""
    Write-Host "Local backups kept at: $BackupDir" -ForegroundColor Gray
    Write-Host "These survive printer firmware updates. Keep them safe." -ForegroundColor Gray
    Write-Host ""
    Write-Host "To revert later:" -ForegroundColor Gray
    Write-Host "  .\install.ps1 -Host $ip -Revert" -ForegroundColor Gray
} else {
    Write-Err "Installer exited with code $rc"
    Write-Host "Check messages above. Open an issue if stuck:"
    Write-Host "  https://github.com/grant0013/KAMP-K2/issues"
}
exit $rc

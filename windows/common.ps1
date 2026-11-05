# What start.ps1 and dod.ps1 share: messages, Docker Desktop, the board, the
# serial bridge (tech-spec 6.2-6.3). Dot-sourced:  . "$PSScriptRoot\common.ps1"
#
# Docker Desktop can't hand a COM port to a container, so the board always
# goes through src/hcl/bridge/serial-bridge.ps1: COMx <-> TCP 7777 on this
# PC, and the container connects to socket://host.docker.internal:7777.
#
# Keep this file ASCII: Windows PowerShell reads a file without a BOM as the
# local code page.

$Root = Split-Path -Parent $PSScriptRoot
$TcpPort = 7777
$BridgeUrl = "socket://host.docker.internal:$TcpPort"
$BoardIds = @(
    "VID_10C4&PID_EA60",  # CP2102 (the board)
    "VID_1A86&PID_7523",  # CH340, in case of a replacement board
    "VID_1A86&PID_55D4"   # CH9102
)
$Work = Join-Path $env:TEMP "dod2026"
$BridgeScript = Join-Path $Root "src\hcl\bridge\serial-bridge.ps1"

function Say([string]$msg) { Write-Host "dod: $msg" }
function Warn([string]$msg) { Write-Host "dod: $msg" -ForegroundColor Yellow }
function Fail([string]$msg) {
    Write-Host "dod: $msg" -ForegroundColor Red
    exit 1
}

# --- Docker -------------------------------------------------------------------

function Docker-Ready {
    & docker info *> $null
    return ($LASTEXITCODE -eq 0)
}

# Docker Desktop running, started and waited for if it isn't
function Ensure-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Fail "Docker Desktop isn't installed (tech-spec 6.1)"
    }
    if (Docker-Ready) { return }
    $desktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path -LiteralPath $desktop)) { Fail "Docker isn't running and Docker Desktop wasn't found at $desktop" }
    Say "starting Docker Desktop (this can take a minute)..."
    Start-Process -FilePath $desktop | Out-Null
    $deadline = (Get-Date).AddMinutes(3)
    while (-not (Docker-Ready)) {
        if ((Get-Date) -gt $deadline) { Fail "Docker Desktop didn't start within 3 minutes" }
        Start-Sleep -Seconds 2
    }
}

# --- the board and the bridge -------------------------------------------------

# The board's COM port, by its USB id; $null when it isn't plugged in
function Find-Board {
    $devices = Get-CimInstance -ClassName Win32_PnPEntity -Filter "Name LIKE '%(COM%'" -ErrorAction SilentlyContinue
    foreach ($d in @($devices)) {
        if (-not $d) { continue }
        foreach ($id in $BoardIds) {
            if ("$($d.PNPDeviceID)" -like "*$id*" -and "$($d.Name)" -match "\((COM\d+)\)") {
                return $Matches[1]
            }
        }
    }
    return $null
}

function Stop-OldBridges {
    $old = Get-CimInstance -ClassName Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { "$($_.CommandLine)" -like "*serial-bridge.ps1*" -and $_.ProcessId -ne $PID }
    foreach ($p in @($old)) {
        if ($p) {
            Say "stopping a bridge left over from the last run (pid $($p.ProcessId))"
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
}

# The bridge in a hidden window; it stops by itself when this script's process ends
function Start-Bridge([string]$com, [string]$log) {
    $argList = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", "`"$BridgeScript`"",
        "-Port", $com, "-TcpPort", $TcpPort,
        "-LogFile", "`"$log`"",
        "-ParentPid", $PID
    )
    return Start-Process -FilePath "powershell.exe" -ArgumentList $argList -WindowStyle Hidden -PassThru
}

function Show-LogTail([string]$path, [int]$lines = 15) {
    if (Test-Path -LiteralPath $path) {
        Get-Content -LiteralPath $path -Tail $lines | ForEach-Object { Write-Host "    $_" }
    }
}

# Starts the bridge for $com and checks it stayed up; returns its process
function Open-Bridge([string]$com, [string]$log) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null
    Stop-OldBridges
    Remove-Item -LiteralPath $log -ErrorAction SilentlyContinue
    $bridge = Start-Bridge $com $log
    Start-Sleep -Milliseconds 1500
    if ($bridge.HasExited) {
        Show-LogTail $log
        Fail "the serial bridge stopped right away (log: $log)"
    }
    Say "bridge running: $com <-> 127.0.0.1:$TcpPort"
    return $bridge
}

function Close-Bridge($bridge) {
    if ($bridge -and -not $bridge.HasExited) {
        Stop-Process -Id $bridge.Id -Force -ErrorAction SilentlyContinue
    }
}

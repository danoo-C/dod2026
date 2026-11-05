<#
.SYNOPSIS
    Starts the DOD 2026 stand on the notebook (tech-spec 6.3). start.bat runs this.

.DESCRIPTION
    1. starts Docker Desktop if it isn't running and waits for it
    2. finds the board's COM port by its USB id, or waits for it
    3. starts the serial <-> TCP bridge (src/hcl/bridge/serial-bridge.ps1)
    4. builds the image if it's missing (needs internet, once)
    5. finds the hotspot's address, name and password; makes a random key
       for the internal pages
    6. runs the container
    7. opens the main screen in Edge, full screen
    8. when that window is closed or Ctrl+C is pressed: stops the container
       and the bridge

    Logs of the last run: %TEMP%\dod2026\ (bridge.log, backend.log).
    Keep this file ASCII: Windows PowerShell reads a file without a BOM as
    the local code page.

.PARAMETER Port
    The board's COM port, if finding it by its USB id doesn't work.
.PARAMETER Simulated
    No board: the simulated one inside the container, no bridge.
.PARAMETER Rebuild
    Build the image again, also when it exists (after the code changed).
.PARAMETER WifiSsid
    The hotspot's name for the Wi-Fi QR code, if reading it from Windows fails.
.PARAMETER WifiPassword
    The hotspot's password, with -WifiSsid.

.EXAMPLE
    start.bat
.EXAMPLE
    start.bat -Simulated
.EXAMPLE
    start.bat -Port COM5 -Rebuild
#>
param(
    [string]$Port = "",
    [switch]$Simulated,
    [switch]$Rebuild,
    [string]$WifiSsid = "",
    [string]$WifiPassword = ""
)

Set-StrictMode -Version 2
# Not "Stop": Windows PowerShell 5.1 turns a native command's stderr into
# errors, and docker writes progress there. Failures are checked by hand.
$ErrorActionPreference = "Continue"

$Root = Split-Path -Parent $PSScriptRoot
$Image = "dod2026-notebook"
$Container = "dod2026"
$HttpPort = 8000
$TcpPort = 7777
$BoardIds = @(
    "VID_10C4&PID_EA60",  # CP2102 (the board)
    "VID_1A86&PID_7523",  # CH340, in case of a replacement board
    "VID_1A86&PID_55D4"   # CH9102
)
$Work = Join-Path $env:TEMP "dod2026"
$BridgeScript = Join-Path $Root "src\hcl\bridge\serial-bridge.ps1"
$BridgeLog = Join-Path $Work "bridge.log"
$BackendLog = Join-Path $Work "backend.log"
$EdgeProfile = Join-Path $Work "edge"

function Say([string]$msg) { Write-Host "dod: $msg" }
function Warn([string]$msg) { Write-Host "dod: $msg" -ForegroundColor Yellow }
function Fail([string]$msg) {
    Write-Host "dod: $msg" -ForegroundColor Red
    exit 1
}

# --- helpers ----------------------------------------------------------------

function Docker-Ready {
    & docker info *> $null
    return ($LASTEXITCODE -eq 0)
}

function Container-Running {
    $state = & docker inspect -f "{{.State.Running}}" $Container 2> $null
    return ($LASTEXITCODE -eq 0 -and "$state".Trim() -eq "true")
}

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

function Stop-OldEdge {
    # an Edge still open on our profile would take the new window over, and
    # the process we start would exit at once
    $old = Get-CimInstance -ClassName Win32_Process -Filter "Name = 'msedge.exe'" -ErrorAction SilentlyContinue |
        Where-Object { "$($_.CommandLine)" -like "*$EdgeProfile*" }
    foreach ($p in @($old)) {
        if ($p) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    }
}

function Start-Bridge([string]$com) {
    $argList = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", "`"$BridgeScript`"",
        "-Port", $com, "-TcpPort", $TcpPort,
        "-LogFile", "`"$BridgeLog`"",
        "-ParentPid", $PID
    )
    return Start-Process -FilePath "powershell.exe" -ArgumentList $argList -WindowStyle Hidden -PassThru
}

function Show-LogTail([string]$path, [int]$lines = 15) {
    if (Test-Path -LiteralPath $path) {
        Get-Content -LiteralPath $path -Tail $lines | ForEach-Object { Write-Host "    $_" }
    }
}

# The address phones use: the hotspot's (normally 192.168.137.1), else the
# notebook's main network address.
function Find-Address {
    $hotspot = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -like "192.168.137.*" } | Select-Object -First 1
    if ($hotspot) { return @{ Ip = $hotspot.IPAddress; Hotspot = $true } }
    $route = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
        Sort-Object RouteMetric | Select-Object -First 1
    if ($route) {
        $ip = Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $route.ifIndex -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($ip) { return @{ Ip = $ip.IPAddress; Hotspot = $false } }
    }
    return @{ Ip = "localhost"; Hotspot = $false }
}

# The Mobile Hotspot's name and password, through the same Windows API the
# Settings page uses. $null when it can't be read. (verify on the notebook)
function Read-Hotspot {
    try {
        $null = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]
        $null = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]
        $conn = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
        if (-not $conn) { return $null }
        $tm = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($conn)
        $cfg = $tm.GetCurrentAccessPointConfiguration()
        return @{ Ssid = "$($cfg.Ssid)"; Password = "$($cfg.Passphrase)" }
    } catch {
        return $null
    }
}

function New-Key {
    $bytes = New-Object byte[] 18
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    return [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_")
}

function Find-Edge {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe"
    )
    return $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
}

# --- the run ----------------------------------------------------------------

$bridge = $null
$browser = $null
$started = $false

New-Item -ItemType Directory -Force -Path $Work | Out-Null
Set-Location -LiteralPath $Root

try {
    # 1. Docker
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Fail "Docker Desktop isn't installed (tech-spec 6.1)"
    }
    if (-not (Docker-Ready)) {
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
    Say "Docker is running"

    # leftovers from a run that didn't stop cleanly (the window closed with X)
    Stop-OldBridges
    & docker rm -f $Container *> $null

    # 2. + 3. the board and the bridge
    if ($Simulated) {
        $serialUrl = "sim"
        Warn "simulated board: nothing goes to the real strip"
    } else {
        $com = $Port
        if (-not $com) {
            $com = Find-Board
            if (-not $com) {
                Warn "the board isn't plugged in: plug its USB cable into the notebook (Ctrl+C to stop; start.bat -Simulated runs without it)"
                while (-not $com) {
                    Start-Sleep -Seconds 2
                    $com = Find-Board
                }
            }
        }
        Say "board on $com"
        Remove-Item -LiteralPath $BridgeLog -ErrorAction SilentlyContinue
        $bridge = Start-Bridge $com
        Start-Sleep -Milliseconds 1500
        if ($bridge.HasExited) {
            Show-LogTail $BridgeLog
            Fail "the serial bridge stopped right away (log: $BridgeLog)"
        }
        $serialUrl = "socket://host.docker.internal:$TcpPort"
        Say "bridge running: $com <-> 127.0.0.1:$TcpPort"
    }

    # 4. the image
    & docker image inspect $Image *> $null
    if ($Rebuild -or $LASTEXITCODE -ne 0) {
        Say "building the image (needs internet; a few minutes the first time)..."
        & docker build -t $Image $Root
        if ($LASTEXITCODE -ne 0) { Fail "the image didn't build; is the notebook online?" }
    }

    # 5. the address, the hotspot, the key
    $addr = Find-Address
    if (-not $addr.Hotspot) {
        Warn "the Mobile Hotspot looks off (no 192.168.137.x address): turn it on in Settings > Network > Mobile hotspot"
        Warn "using $($addr.Ip) for the page's QR code meanwhile"
    }
    $publicUrl = "http://$($addr.Ip):$HttpPort"

    if (-not $WifiSsid) {
        $hs = Read-Hotspot
        if ($hs) {
            $WifiSsid = $hs.Ssid
            $WifiPassword = $hs.Password
        }
    }
    $wifiOk = $WifiSsid.Length -ge 1 -and $WifiSsid.Length -le 32 -and $WifiPassword.Length -ge 8 -and $WifiPassword.Length -le 63
    if ($WifiSsid -and -not $wifiOk) {
        Warn "the hotspot's name or password doesn't fit WPA2 (name 1-32, password 8-63 characters): no Wi-Fi QR code"
    } elseif (-not $WifiSsid) {
        Warn "couldn't read the hotspot's name and password: no Wi-Fi QR code (start.bat -WifiSsid NAME -WifiPassword PASS)"
    }
    $key = New-Key

    # 6. the container; values go through the environment, so no quoting can break them
    $cache = Join-Path $Root "cache"
    New-Item -ItemType Directory -Force -Path $cache | Out-Null
    $songs = @(Get-ChildItem -LiteralPath $cache -Filter "*.mp4" -ErrorAction SilentlyContinue).Count
    if ($songs -eq 0) { Warn "cache\ has no songs: the music mode will be empty (./dod songs in WSL, then copy cache\ over)" }

    $env:DOD_SERIAL = $serialUrl
    $env:DOD_PUBLIC_URL = $publicUrl
    $env:DOD_INTERNAL_KEY = $key
    $runArgs = @("run", "-d", "--init", "--name", $Container, "-p", "${HttpPort}:8000",
                 "-v", "${cache}:/work/cache",
                 "-e", "DOD_SERIAL", "-e", "DOD_PUBLIC_URL", "-e", "DOD_INTERNAL_KEY")
    if ($wifiOk) {
        $env:DOD_WIFI_SSID = $WifiSsid
        $env:DOD_WIFI_PASSWORD = $WifiPassword
        $runArgs += @("-e", "DOD_WIFI_SSID", "-e", "DOD_WIFI_PASSWORD")
    }
    & docker @runArgs $Image | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "the container didn't start (is port $HttpPort taken?)" }
    $started = $true

    Say "waiting for the backend..."
    $deadline = (Get-Date).AddSeconds(60)
    while ($true) {
        try {
            $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri "http://localhost:$HttpPort/api/status"
            break
        } catch { }
        if (-not (Container-Running)) {
            & docker logs --tail 30 $Container
            Fail "the backend stopped while starting (its log is above)"
        }
        if ((Get-Date) -gt $deadline) { Fail "the backend didn't answer within 60 s" }
        Start-Sleep -Milliseconds 500
    }

    # 7. the main screen
    $mainUrl = "http://localhost:$HttpPort/internal/main?key=$key"
    $edge = Find-Edge
    if ($edge) {
        Stop-OldEdge
        $edgeArgs = @("--app=$mainUrl", "--start-fullscreen", "--user-data-dir=`"$EdgeProfile`"",
                      "--no-first-run", "--no-default-browser-check", "--autoplay-policy=no-user-gesture-required")
        $browser = Start-Process -FilePath $edge -ArgumentList $edgeArgs -PassThru
    } else {
        Warn "Edge wasn't found: open the main screen by hand"
    }

    Write-Host ""
    Say "the stand is running"
    Say "  phones:       $publicUrl"
    Say "  main screen:  $mainUrl"
    Say "  logging page: http://localhost:$HttpPort/internal/logging?key=$key"
    Say "close the main screen's window (Alt+F4) or press Ctrl+C here to stop"
    Write-Host ""

    # 8. keep watch until the window closes
    while ($true) {
        Start-Sleep -Seconds 2
        if ($browser -and $browser.HasExited) {
            Say "the main screen was closed"
            break
        }
        if (-not (Container-Running)) {
            & docker logs --tail 30 $Container
            Warn "the backend stopped (its log is above)"
            break
        }
        if ($bridge -and $bridge.HasExited) {
            Warn "the serial bridge stopped; starting it again"
            Show-LogTail $BridgeLog 5
            $bridge = Start-Bridge $com
        }
    }
} finally {
    Say "stopping..."
    if ($started) {
        & docker logs $Container *> $BackendLog
        & docker rm -f $Container *> $null
    }
    if ($bridge -and -not $bridge.HasExited) {
        Stop-Process -Id $bridge.Id -Force -ErrorAction SilentlyContinue
    }
    if ($browser -and -not $browser.HasExited) {
        Stop-Process -Id $browser.Id -Force -ErrorAction SilentlyContinue
    }
    foreach ($name in "DOD_SERIAL", "DOD_PUBLIC_URL", "DOD_INTERNAL_KEY", "DOD_WIFI_SSID", "DOD_WIFI_PASSWORD") {
        Remove-Item -LiteralPath "env:$name" -ErrorAction SilentlyContinue
    }
    Say "stopped (logs: $Work)"
}

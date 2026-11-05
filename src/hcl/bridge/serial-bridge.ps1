<#
.SYNOPSIS
    Serial <-> TCP bridge between the board's COM port and the container
    (docs/hcl.md 8, tech-spec 6.2 A).

.DESCRIPTION
    Docker Desktop can't pass a COM port into a container, so this script
    opens it and copies bytes both ways, unchanged, to one TCP client: the
    backend, at socket://host.docker.internal:7777.

    - the COM port is opened at 115200 with DTR and RTS off
    - one client at a time; a new client replaces the old one (a restarted
      container must never wait behind its own dead connection)
    - the COM port stays open when the client goes, so a backend restart
      doesn't reset the board
    - when the board is unplugged, the client is dropped and the script
      waits for the port to come back
    - with -ParentPid it stops by itself when that process (start.ps1) ends

    Only what Windows has built in: Windows PowerShell 5.1 and .NET.
    Keep this file ASCII: Windows PowerShell reads a file without a BOM as
    the local code page.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File serial-bridge.ps1 -Port COM3
#>
param(
    [Parameter(Mandatory = $true)][string]$Port,
    [int]$TcpPort = 7777,
    [string]$Listen = "127.0.0.1",
    [int]$Baud = 115200,
    [string]$LogFile = "",
    [int]$ParentPid = 0
)

Set-StrictMode -Version 2
$ErrorActionPreference = "Stop"

$Task = [System.Threading.Tasks.Task]
$SerialPort = [System.IO.Ports.SerialPort]

function Log([string]$msg) {
    $line = "{0} bridge: {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    Write-Host $line
    if ($LogFile) {
        try { Add-Content -LiteralPath $LogFile -Value $line } catch { }
    }
}

# The innermost message: PowerShell wraps .NET exceptions in its own.
function Reason($err) {
    $e = $err
    if ($e -is [System.Management.Automation.ErrorRecord]) { $e = $e.Exception }
    while ($e.InnerException) { $e = $e.InnerException }
    return $e.Message
}

# A finished task's value; GetResult throws the real exception, not an AggregateException.
function Result($t) {
    return $t.GetAwaiter().GetResult()
}

function Port-Present {
    return ($SerialPort::GetPortNames() -contains $Port)
}

function Parent-Gone {
    if ($ParentPid -le 0) { return $false }
    return -not (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue)
}

function Open-Serial {
    $sp = New-Object System.IO.Ports.SerialPort -ArgumentList $Port, $Baud, ([System.IO.Ports.Parity]::None), 8, ([System.IO.Ports.StopBits]::One)
    $sp.Handshake = [System.IO.Ports.Handshake]::None
    $sp.DtrEnable = $false   # set before Open(): DTR/RTS toggling resets an ESP32
    $sp.RtsEnable = $false
    $sp.ReadBufferSize = 65536
    $sp.Open()
    # .NET Framework bug: when a USB serial adapter is unplugged, the port's
    # stream throws from its finalizer and takes the whole process down. We
    # close it ourselves, so its finalizer never needs to run.
    [GC]::SuppressFinalize($sp.BaseStream)
    return $sp
}

# --- state ------------------------------------------------------------------

$script:serial = $null      # the open SerialPort, or $null while there is no board
$script:sStream = $null
$script:sRead = $null       # the pending read from the board
$sBuf = New-Object byte[] 4096

$script:client = $null      # the TcpClient, or $null
$script:net = $null
$script:tRead = $null       # the pending read from the client
$tBuf = New-Object byte[] 4096
$script:toBoard = 0
$script:fromBoard = 0
$script:since = $null

function Drop-Client([string]$why) {
    if (-not $script:client) { return }
    $secs = [int]((Get-Date) - $script:since).TotalSeconds
    Log ("client {0} after {1} s ({2} bytes to the board, {3} from it)" -f $why, $secs, $script:toBoard, $script:fromBoard)
    try { $script:client.Close() } catch { }
    $script:client = $null
    $script:net = $null
    $script:tRead = $null
}

function Take-Client($c) {
    if ($script:client) { Drop-Client "replaced by a new one" }
    $c.NoDelay = $true   # small messages, sent at once: latency matters more than packets
    $script:client = $c
    $script:net = $c.GetStream()
    $script:tRead = $script:net.ReadAsync($tBuf, 0, $tBuf.Length)
    $script:toBoard = 0
    $script:fromBoard = 0
    $script:since = Get-Date
    Log ("client connected from {0}" -f $c.Client.RemoteEndPoint)
}

function Close-Serial([string]$why) {
    Drop-Client "dropped: $why"
    if ($script:serial) {
        try { $script:serial.Close() } catch { }
    }
    $script:serial = $null
    $script:sStream = $null
    $script:sRead = $null
    Log "$Port closed: $why"
}

# --- main loop --------------------------------------------------------------

try {
    $listener = New-Object System.Net.Sockets.TcpListener -ArgumentList ([System.Net.IPAddress]::Parse($Listen)), $TcpPort
    $listener.Start()
} catch {
    Log ("can't listen on {0}:{1}: {2} (is another bridge still running?)" -f $Listen, $TcpPort, (Reason $_))
    exit 1
}
Log ("listening on {0}:{1} for {2} at {3} baud" -f $Listen, $TcpPort, $Port, $Baud)
$accept = $listener.AcceptTcpClientAsync()
$saidWaiting = $false

try {
    while ($true) {
        if (Parent-Gone) {
            Log "the launcher is gone, stopping"
            break
        }

        # --- no board: try to open it, turn clients away meanwhile
        if (-not $script:serial) {
            if ($accept.IsCompleted) {
                try { (Result $accept).Close() } catch { }
                $accept = $listener.AcceptTcpClientAsync()
            }
            if (Port-Present) {
                try {
                    $script:serial = Open-Serial
                    $script:sStream = $script:serial.BaseStream
                    $script:sRead = $script:sStream.ReadAsync($sBuf, 0, $sBuf.Length)
                    Log "$Port open"
                    $saidWaiting = $false
                    continue
                } catch {
                    $script:serial = $null
                    if (-not $saidWaiting) { Log ("can't open {0} yet: {1}" -f $Port, (Reason $_)) }
                }
            } elseif (-not $saidWaiting) {
                Log "waiting for $Port (plug the board in)"
            }
            $saidWaiting = $true
            Start-Sleep -Milliseconds 500
            continue
        }

        # --- the board is there: wait for whichever side has something
        if ($script:client) {
            $tasks = [System.Threading.Tasks.Task[]]@($script:sRead, $script:tRead, $accept)
        } else {
            $tasks = [System.Threading.Tasks.Task[]]@($script:sRead, $accept)
        }
        $i = $Task::WaitAny($tasks, 500)

        try {
            if ($i -lt 0) {
                # nothing for half a second: is the board still plugged in?
                if (-not (Port-Present)) { throw "$Port disappeared" }
            } elseif ([object]::ReferenceEquals($tasks[$i], $script:sRead)) {
                # board -> client
                $n = Result $script:sRead
                if ($n -le 0) { throw "the port stopped reading" }
                if ($script:client) {
                    try {
                        $script:net.Write($sBuf, 0, $n)
                        $script:fromBoard += $n
                    } catch {
                        Drop-Client ("lost: " + (Reason $_))
                    }
                }  # else: nobody listens; the backend flushes its input when it connects anyway
                $script:sRead = $script:sStream.ReadAsync($sBuf, 0, $sBuf.Length)
            } elseif ($script:client -and [object]::ReferenceEquals($tasks[$i], $script:tRead)) {
                # client -> board
                $n = 0
                try { $n = Result $script:tRead } catch { }
                if ($n -le 0) {
                    Drop-Client "disconnected"
                } else {
                    $script:sStream.Write($tBuf, 0, $n)   # throws if the board is gone: handled below
                    $script:toBoard += $n
                    $script:tRead = $script:net.ReadAsync($tBuf, 0, $tBuf.Length)
                }
            } else {
                # a new client
                $c = $null
                try { $c = Result $accept } catch { }
                $accept = $listener.AcceptTcpClientAsync()
                if ($c) {
                    # its own try: a client failing here is no reason to close the board
                    try { Take-Client $c } catch {
                        Log ("client turned away: " + (Reason $_))
                        try { $c.Close() } catch { }
                        $script:client = $null
                        $script:net = $null
                        $script:tRead = $null
                    }
                }
            }
        } catch {
            Close-Serial (Reason $_)
        }
    }
} finally {
    Drop-Client "dropped: the bridge stopped"
    if ($script:serial) { try { $script:serial.Close() } catch { } }
    try { $listener.Stop() } catch { }
    Log "stopped"
}

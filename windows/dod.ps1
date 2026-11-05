<#
.SYNOPSIS
    The dev wrapper on Windows: the same commands as ./dod in WSL. dod.bat runs this.

.DESCRIPTION
    dod.bat --help lists the commands, dod.bat --manual explains them. Every
    tool runs in Docker Desktop, nothing else is installed.

    What is different from ./dod, because this is Windows:
    - the board: Docker Desktop can't hand a COM port to a container, so the
      serial bridge (src/hcl/bridge/serial-bridge.ps1) runs while a command
      needs the board, and the container talks to it over TCP.
      DOD_SERIAL takes COM5 (that port) or board (the board, found by its USB
      id); ESP_PORT=COM5 picks the port for the hcl and esp commands.
    - settings: set DOD_BRIGHTNESS=0.3 (cmd) or $env:DOD_BRIGHTNESS=0.3
      (PowerShell) before the command, instead of DOD_BRIGHTNESS=0.3 ./dod sim
    - reloading: the backend and Vite poll for file changes (Docker Desktop
      doesn't pass a Windows folder's changes into the container)
    - files written in the project belong to you anyway (no --user needed)

    Keep this file ASCII: Windows PowerShell reads a file without a BOM as
    the local code page.
#>
# No param block: every argument goes through as typed (pytest's -k, -x ...).

Set-StrictMode -Version 2
# Not "Stop": Windows PowerShell 5.1 turns a native command's stderr into
# errors, and docker writes progress there. Exit codes are checked by hand.
$ErrorActionPreference = "Continue"

. "$PSScriptRoot\common.ps1"  # $Root, $BridgeUrl, $Work, Say/Warn/Fail, Docker, the board, the bridge

$Argv = @($args)
$Image = "dod2026"
$NodeImage = "node:22.23.4-slim"
$NpmCache = "dod2026-npm"  # Docker volume
$Network = "dod2026-dev"  # dod sim and dev: Vite reaches the backend by its container name
$Frontend = "src/frontend"
$HclTools = @("monitor", "pattern", "bench", "repl")
$Suites = @("hcl", "backend", "frontend")
$PortHttp = 8000
$PortVite = 5173
$BridgeLog = Join-Path $Work "dod-bridge.log"

# The backend with reloading. The settings are checked once before uvicorn
# starts: with --reload, a bad one would otherwise leave the reloader waiting
# for a file change that can't fix an environment variable. (No double quotes
# inside: Windows PowerShell 5.1 passes them to docker broken.)
$BackendCmd = @("sh", "-c", ("python -c 'from dod.main import settings_or_exit; settings_or_exit()' && " +
    "exec uvicorn --factory dod.main:create_app --host 0.0.0.0 --port $PortHttp " +
    "--reload --reload-dir src/backend --reload-dir src/hcl --ws-max-size 65536"))

$script:Bridge = $null

function Show-Help {
    Write-Host @'
DOD 2026 dev wrapper on Windows: the same commands as ./dod in WSL. Every tool
runs in Docker Desktop, nothing else is installed.

usage: dod <command> [args]      (in the project folder; dod.bat in PowerShell: .\dod)

Run the app
  sim                                     backend + Vite on http://localhost:5173, simulated board
  dev                                     the same with the real board (through the bridge; or DOD_SERIAL)
  backend                                 the backend alone on http://localhost:8000 (serves the last frontend-build)
  notebook                                the notebook's self-contained image, on http://localhost:8000

Test
  test [hcl|backend|frontend] [args]      all three suites, or one; extra args go to pytest / Vitest
  backend-soak [--minutes N|--seconds N]  the soak test: a simulated open day (default 30 min)

Build
  build                                   (re)build the dev image
  frontend-build                          build the frontend into src/frontend/dist (what backend serves)
  schema                                  write the WebSocket JSON Schema and the TypeScript types
  npm <args>                              any npm command, in a Node container, in src/frontend

Songs
  songs [id ...]                          download the songs from songs.txt missing from cache\, make their light shows

The board
  hcl monitor [--send] [--seconds N]      watch the link: a status line every second, every event
  hcl pattern [--speed X]                 wiring test: colours, the strip, the 8x8's rows and columns
  hcl bench [--seconds N] [--max-fps N]   speed test, ends with PASS or FAIL
  hcl repl                                ask main.py to step aside, for the Python prompt
  esp upload                              put src/hcl/esp/ (and protocol.py) on the board, reset it
  esp run <file.py>                       run a MicroPython script on the board, its output here
  esp repl                                a Python prompt on the board

Other
  shell                                   a bash shell in the container
  -h, --help                              this list
  --manual                                how to use each command, and full commands to launch the app

The open day itself: start.bat (Docker, the board, the image, Edge full screen).

Settings: any DOD_* variable reaches the backend:
  cmd:         set DOD_BRIGHTNESS=0.3  then  dod sim
  PowerShell:  $env:DOD_BRIGHTNESS="0.3"; .\dod sim
DOD_SERIAL picks the board: sim (default), COM5, board (found by its USB id), socket://host:port.
'@
}

function Show-Manual {
    Write-Host @'
DOD 2026 - MANUAL, on Windows
=============================

dod.bat has the same commands as ./dod in WSL; the manual below is ./dod's.
Read it with these changes:

  ./dod sim                        ->  dod sim  (cmd)  or  .\dod sim  (PowerShell), in the project folder
  DOD_BRIGHTNESS=0.3 ./dod sim     ->  set DOD_BRIGHTNESS=0.3  then  dod sim   (cmd; the setting stays
                                       for that window: set DOD_BRIGHTNESS=  removes it)
                                       $env:DOD_BRIGHTNESS="0.3"; .\dod sim     (PowerShell)
  /dev/ttyUSB0, usbipd             ->  not needed: plug the board in. Commands that need it start the
                                       serial bridge (COMx <-> TCP 7777) and stop it afterwards.
                                       DOD_SERIAL=COM5 or ESP_PORT=COM5 picks a port, DOD_SERIAL=board
                                       the board found by its USB id. Log: %TEMP%\dod2026\dod-bridge.log
  WSL, ~/spseke/dod2026            ->  the project folder on Windows
  1.6 (real phones)                ->  no WSL forwarding: Windows Firewall must allow port 5173 (or 8000)

  Docker Desktop is started by itself if it isn't running.

'@
    $source = Get-Content -Raw -LiteralPath (Join-Path $Root "dod")
    if ($source -match "(?s)show_manual\(\) \{\s*cat <<'EOF'\r?\n(.*?)\r?\nEOF") {
        Write-Host $Matches[1]
    } else {
        Warn "couldn't read the manual from the dod script"
    }
}

# --- helpers --------------------------------------------------------------------

function Is-Interactive {
    return (-not [Console]::IsInputRedirected -and -not [Console]::IsOutputRedirected)
}

# Windows' quoting rules for one argument (what docker.exe parses)
function Quote-Arg([string]$a) {
    if ($a -ne "" -and $a -notmatch '[\s"]') { return $a }
    $out = '"'
    $slashes = 0
    foreach ($ch in $a.ToCharArray()) {
        if ($ch -eq '\') { $slashes++; continue }
        if ($ch -eq '"') { $out += ('\' * (2 * $slashes + 1)) + '"' }
        else { $out += ('\' * $slashes) + $ch }
        $slashes = 0
    }
    return $out + ('\' * (2 * $slashes)) + '"'
}

# docker in the background, its output in this window (dod sim, dod dev)
function Start-Docker([string[]]$list) {
    $line = ($list | ForEach-Object { Quote-Arg $_ }) -join " "
    return Start-Process -FilePath "docker" -ArgumentList $line -NoNewWindow -PassThru
}

function Image-Exists([string]$name) {
    & docker image inspect $name *> $null
    return ($LASTEXITCODE -eq 0)
}

# The board's port: ESP_PORT, else the board found by its USB id; $null without one
function Find-Port {
    if ($env:ESP_PORT) { return $env:ESP_PORT }
    return Find-Board
}

# What the container gets as DOD_SERIAL. A COM port (or "board") starts the
# bridge, and the container gets the bridge's address.
function Resolve-Serial([string]$value) {
    if ($value -eq "board") {
        $com = Find-Port
        if (-not $com) { Fail "no board found: plug in its USB cable (or DOD_SERIAL=COM5 for another port)" }
        $value = $com
    }
    if ($value -match '^COM\d+$') {
        if (-not $script:Bridge) { $script:Bridge = Open-Bridge $value $BridgeLog }
        return $BridgeUrl
    }
    if ($value -like "/dev/*") { Fail "DOD_SERIAL=${value}: on Windows the board is COM5 (or board, found by its USB id)" }
    return $value
}

# docker run arguments shared by every command (./dod's docker_args)
function Docker-Args([string]$serial) {
    if (-not (Image-Exists $Image)) {
        & docker build --target dev -t $Image $Root
        if ($LASTEXITCODE -ne 0) { Fail "the dev image didn't build" }
    }
    $a = @("--rm", "--init", "-i", "-v", "${Root}:/work", "-w", "/work",
           "-e", "HOME=/tmp", "-e", "PYTHONUNBUFFERED=1", "-e", "DOD_SERIAL=$serial")
    # every other DOD_ setting from this window goes in too (docs/backend.md 11)
    foreach ($v in @(Get-ChildItem env: | Where-Object { $_.Name -like "DOD_*" -and $_.Name -ne "DOD_SERIAL" })) {
        $a += @("-e", $v.Name)
    }
    if ($serial -eq $BridgeUrl) { $a += @("-e", "ESPTOOL_PORT=$serial") }  # the esp commands' port
    if (Is-Interactive) { $a += "-t" }
    return ,$a
}

# docker run arguments for the Node container, in src/frontend
function Node-Args {
    & docker volume inspect $NpmCache *> $null
    if ($LASTEXITCODE -ne 0) { & docker volume create $NpmCache | Out-Null }
    $n = @("--rm", "--init", "-i", "-v", "${Root}:/work", "-w", "/work/$Frontend", "-e", "HOME=/tmp",
           "-v", "${NpmCache}:/cache", "-e", "npm_config_cache=/cache",
           "-e", "npm_config_update_notifier=false", "-e", "npm_config_fund=false")
    if (Is-Interactive) { $n += "-t" }
    return ,$n
}

# npm ci when node_modules is missing or older than the lock file
function Ensure-NodeModules($nargs) {
    $lock = Join-Path $Root "src\frontend\package-lock.json"
    $installed = Join-Path $Root "src\frontend\node_modules\.package-lock.json"
    if (-not (Test-Path -LiteralPath $installed) -or
            (Get-Item -LiteralPath $lock).LastWriteTime -gt (Get-Item -LiteralPath $installed).LastWriteTime) {
        Say "installing the frontend's packages (npm ci)"
        & docker run @nargs $NodeImage npm ci
        if ($LASTEXITCODE -ne 0) { Fail "npm ci failed" }
    }
}

function Without-Terminal($list) {
    return ,@($list | Where-Object { $_ -ne "-t" -and $_ -ne "-i" })
}

# dod sim and dod dev: the backend and Vite side by side, both printing here.
# The browser only talks to Vite (5173), which forwards /api, /ws and /media.
# Ctrl+C stops both.
function Dev-Stack([string]$serialValue) {
    $serial = Resolve-Serial $serialValue
    # the pages come from Vite here: the printed links and the QR code point at it
    if (-not $env:DOD_PUBLIC_URL) { $env:DOD_PUBLIC_URL = "http://localhost:$PortVite" }
    $a = Docker-Args $serial
    $n = Node-Args
    Ensure-NodeModules $n
    & docker network inspect $Network *> $null
    if ($LASTEXITCODE -ne 0) { & docker network create $Network | Out-Null }
    $running = (& docker ps --filter "name=^dod2026-(backend|vite)$" --format "{{.Names}}") -join " "
    if ($running) { Fail "already running: $running (another dod sim or dod backend); stop it first" }
    $key = if ($env:DOD_INTERNAL_KEY) { $env:DOD_INTERNAL_KEY } else { "dev" }
    # neither gets a terminal or stdin: with two containers in one window,
    # a terminal would put the window into raw mode and break the other's lines
    $bg = Without-Terminal $a
    $fg = Without-Terminal $n
    try {
        $backend = Start-Docker (@("run") + $bg + @("--name", "dod2026-backend", "--network", $Network,
            "-p", "${PortHttp}:${PortHttp}", "-e", "DOD_INTERNAL_KEY=$key", "-e", "WATCHFILES_FORCE_POLLING=true",
            $Image) + $BackendCmd)
        Say "http://localhost:$PortVite  (internal pages: /internal/main?key=$key, /internal/logging?key=$key)"
        $vite = Start-Docker (@("run") + $fg + @("--name", "dod2026-vite", "--network", $Network,
            "-p", "${PortVite}:${PortVite}", "-e", "DOD_BACKEND=http://dod2026-backend:$PortHttp", "-e", "DOD_POLL=1",
            $NodeImage, "npx", "vite", "--host", "0.0.0.0", "--port", "$PortVite", "--strictPort"))
        # until Ctrl+C, or until either one ends by itself
        while (-not $backend.HasExited -and -not $vite.HasExited) { Start-Sleep -Milliseconds 500 }
    } finally {
        Say "stopping"
        & docker stop dod2026-backend dod2026-vite *> $null
    }
}

function Run-Tests($rest) {
    $rest = @($rest | ForEach-Object { if ($_ -like "src\*") { $_ -replace '\\', '/' } else { $_ } })
    $suites = $Suites
    $picked = ""
    $paths = $false
    if ($rest.Count -gt 0 -and $Suites -contains $rest[0]) {
        $picked = $rest[0]
        $rest = @($rest | Select-Object -Skip 1)
    }
    # a path inside one suite picks that suite
    foreach ($arg in $rest) {
        foreach ($s in $Suites) {
            if ($arg -eq "src/$s" -or $arg -like "src/$s/*") {
                $paths = $true
                if ($picked -and $picked -ne $s) { Fail "'$arg' is not in the $picked suite; run one suite at a time" }
                $picked = $s
            }
        }
    }
    if ($picked) { $suites = @($picked) }

    $a = Docker-Args (Resolve-Serial $(if ($env:DOD_SERIAL) { $env:DOD_SERIAL } else { "sim" }))
    $result = 0
    foreach ($s in $suites) {
        if ($suites.Count -gt 1) { Write-Host "=== $s (src/$s)" }
        if ($s -eq "frontend") {
            # type check, the generated types' check, then Vitest; arguments only
            # when this suite was picked (pytest's would mean nothing here)
            $vargs = @()
            if ($picked) { $vargs = @($rest | ForEach-Object { $_ -replace "^$Frontend/", "" }) }
            $n = Node-Args
            Ensure-NodeModules $n
            & docker run @n $NodeImage npm test -- @vargs
        } else {
            $cmd = @("python", "-m", "pytest")
            if (-not $paths) { $cmd += "src/$s" }
            & docker run @a $Image @cmd @rest
        }
        $status = $LASTEXITCODE
        if ($status -eq 5) { Write-Host "dod: no tests in src/$s yet" }  # pytest: no tests yet, not a failure
        elseif ($status -ne 0) { $result = $status }
    }
    return $result
}

# --- the commands --------------------------------------------------------------------

$command = if ($Argv.Count -gt 0) { $Argv[0] } else { "" }
$rest = @($Argv | Select-Object -Skip 1)

# --help and --manual work without Docker
switch ($command) {
    { $_ -in "-h", "--help", "help", "" } { Show-Help; exit 0 }
    { $_ -in "--manual", "manual" } { Show-Manual; exit 0 }
}

$Commands = @("build", "test", "backend", "notebook", "sim", "dev", "npm", "frontend-build", "schema",
               "backend-soak", "songs", "shell", "esp", "hcl")
if ($Commands -notcontains $command) {
    Write-Host "dod: unknown command '$command'" -ForegroundColor Red
    Write-Host "usage: dod <command> [args]   (dod --help lists the commands, dod --manual explains them)"
    exit 1
}

Ensure-Docker
Set-Location -LiteralPath $Root
$code = 0
try {
    switch ($command) {
        "build" {
            & docker build --target dev -t $Image $Root
            $code = $LASTEXITCODE
        }
        "test" {
            $code = Run-Tests $rest
        }
        "backend" {
            $a = Docker-Args (Resolve-Serial $(if ($env:DOD_SERIAL) { $env:DOD_SERIAL } else { "sim" }))
            # the dev key opens the internal pages: /internal/main?key=dev (docs/backend.md 9)
            $key = if ($env:DOD_INTERNAL_KEY) { $env:DOD_INTERNAL_KEY } else { "dev" }
            & docker run @a --name dod2026-backend -p "${PortHttp}:${PortHttp}" -e "DOD_INTERNAL_KEY=$key" `
                -e "WATCHFILES_FORCE_POLLING=true" $Image @BackendCmd
            $code = $LASTEXITCODE
        }
        "notebook" {
            # the image start.bat runs, tried here without the rest of start.bat:
            # nothing mounted but cache\, the simulated board unless DOD_SERIAL says otherwise
            & docker build -t dod2026-notebook $Root
            if ($LASTEXITCODE -ne 0) { Fail "the notebook image didn't build" }
            $serial = Resolve-Serial $(if ($env:DOD_SERIAL) { $env:DOD_SERIAL } else { "sim" })
            $key = if ($env:DOD_INTERNAL_KEY) { $env:DOD_INTERNAL_KEY } else { "dev" }
            $cache = Join-Path $Root "cache"
            $nb = @("--rm", "--init", "-i", "--name", "dod2026-notebook", "-p", "${PortHttp}:${PortHttp}",
                    "-v", "${cache}:/work/cache", "-e", "DOD_SERIAL=$serial", "-e", "DOD_INTERNAL_KEY=$key")
            foreach ($v in @(Get-ChildItem env: | Where-Object { $_.Name -like "DOD_*" -and $_.Name -notin "DOD_SERIAL", "DOD_INTERNAL_KEY" })) {
                $nb += @("-e", $v.Name)
            }
            if (Is-Interactive) { $nb += "-t" }
            & docker run @nb dod2026-notebook
            $code = $LASTEXITCODE
        }
        "sim" {
            Dev-Stack "sim"
        }
        "dev" {
            Dev-Stack $(if ($env:DOD_SERIAL) { $env:DOD_SERIAL } else { "board" })
        }
        "npm" {
            $n = Node-Args
            & docker run @n $NodeImage npm @rest
            $code = $LASTEXITCODE
        }
        "frontend-build" {
            $n = Node-Args
            Ensure-NodeModules $n
            & docker run @n $NodeImage npm run build
            $code = $LASTEXITCODE
        }
        "schema" {
            # the JSON Schema from the Pydantic models, then the TypeScript types from it
            $a = Docker-Args "sim"
            & docker run @a $Image python -m dod.api.schema
            if ($LASTEXITCODE -ne 0) { $code = $LASTEXITCODE; break }
            $n = Node-Args
            Ensure-NodeModules $n
            & docker run @n $NodeImage npm run --silent types
            $code = $LASTEXITCODE
        }
        "backend-soak" {
            # the backend on its own port inside this container: nothing published,
            # so it can run next to dod sim (docs/plans/backend.md, step 10)
            $a = Docker-Args "sim"
            & docker run @a $Image python src/backend/tests/soak.py @rest
            $code = $LASTEXITCODE
        }
        "songs" {
            # into cache\ in the project (DOD_CACHE_DIR, /work/cache); needs the internet
            $a = Docker-Args "sim"
            & docker run @a $Image python -m dod.music.download @rest
            $code = $LASTEXITCODE
        }
        "shell" {
            $a = Docker-Args (Resolve-Serial $(if ($env:DOD_SERIAL) { $env:DOD_SERIAL } else { "sim" }))
            & docker run @a $Image bash
            $code = $LASTEXITCODE
        }
        "esp" {
            # the board's own code (docs/hcl.md 7, 9). main.py turns Ctrl-C off, so
            # first `hcl repl` asks it to step aside (exit 2: it didn't answer, fine
            # when the board is at the >>> prompt already), then mpremote takes over,
            # through the bridge (pyserial's socket://)
            $sub = if ($rest.Count -gt 0) { $rest[0] } else { "" }
            if ($sub -notin "upload", "run", "repl") { Write-Host "usage: dod esp upload | run <file.py> | repl"; exit 2 }
            if ($sub -eq "run" -and $rest.Count -lt 2) { Write-Host "usage: dod esp run <file.py>"; exit 2 }
            $com = Find-Port
            if (-not $com) { Fail "no board found: plug in its USB cable (ESP_PORT=COM5 picks another port)" }
            $a = Docker-Args (Resolve-Serial $com)
            $stepAside = 'python -m hcl.tools.repl --url $ESPTOOL_PORT; s=$?; [ $s -le 2 ] || exit $s'
            switch ($sub) {
                "upload" {
                    & docker run @a $Image sh -c ($stepAside + '
                        cd src/hcl && mpremote connect $ESPTOOL_PORT cp esp/boot.py esp/config.py esp/max7219.py hcl/protocol.py : + cp esp/main.py : + reset')
                }
                "run" {
                    $file = $rest[1] -replace '\\', '/'
                    & docker run @a $Image sh -c ($stepAside + '
                        mpremote connect $ESPTOOL_PORT run $1') sh $file
                }
                "repl" {
                    & docker run @a $Image sh -c ($stepAside + '
                        mpremote connect $ESPTOOL_PORT repl')
                }
            }
            $code = $LASTEXITCODE
        }
        "hcl" {
            $tool = if ($rest.Count -gt 0) { $rest[0] } else { "" }
            if ($HclTools -notcontains $tool) { Fail "unknown HCL tool '$tool', pick one of: $($HclTools -join ' ')" }
            # The tools are for the board: with one plugged in and no DOD_SERIAL given,
            # they talk to it, not to the simulator (set DOD_SERIAL=sim for that).
            $serialValue = $env:DOD_SERIAL
            if (-not $serialValue) {
                $board = Find-Port
                $serialValue = if ($board) { $board } else { "sim" }
                Say "hcl $tool on $(if ($board) { "$board (through the bridge)" } else { 'sim (no board plugged in)' })"
            }
            $a = Docker-Args (Resolve-Serial $serialValue)
            & docker run @a $Image python -m "hcl.tools.$tool" @($rest | Select-Object -Skip 1)
            $code = $LASTEXITCODE
        }
    }
} finally {
    Close-Bridge $script:Bridge
}
exit $code

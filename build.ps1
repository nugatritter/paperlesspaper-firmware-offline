#Requires -Version 5.1
<#
.SYNOPSIS
    Baut die paperlesspaper-Offline-Firmware für das 13,3-Zoll-Display (PlatformIO-Umgebung epd13),
    prüft das App-Image und überträgt es nur auf ausdrücklichen Wunsch per USB.

.DESCRIPTION
    Ablauf:
      1. Umgebung prüfen: PowerShell, Projektdateien, PlatformIO, Git, Speicherplatz, Git-Stand.
      2. Projektkonfiguration prüfen: Umgebung epd13, Build-Flag, Board, Partitionstabelle.
      3. Firmware bauen: optional vorher bereinigen, bei Netzwerkfehlern ein zweiter Versuch.
      4. App-Image prüfen: Header, Chip-ID, App-Beschreibung, SHA-256, Größe gegen die
         App-Partition, Aktualität und Gegenprüfung mit esptool.
      5. Aufgelöste Plattform- und Bibliotheksversionen protokollieren.
      6. Nur mit -Upload: seriellen Port und alle vier Flash-Images prüfen, das Gerät per 'B'
         in den ROM-Bootloader schalten und genau die geprüften Dateien direkt mit esptool
         flashen. PlatformIO wird für den Upload nicht erneut gestartet und baut daher nicht neu.

    Jede Ausgabe wird zusätzlich in .pio\logs\build-epd13-<Zeitstempel>.log geschrieben.
    Ohne -Upload greift das Skript nie auf ein Gerät zu. Mit -Upload -WhatIf wird der Port
    geprüft, das Gerät aber weder angesprochen noch beschrieben.

    Exitcodes:
      0  Erfolg
      1  Unerwarteter Fehler im Skript
      2  Voraussetzungen oder Projektkonfiguration fehlerhaft
      3  Build fehlgeschlagen
      4  App-Image ungültig
      5  Serieller Port fehlt oder gehört nicht zum Zielgerät
      6  Upload fehlgeschlagen
      7  Gerät nicht in den ROM-Bootloader gekommen

.PARAMETER Upload
    Baut, prüft und überträgt die Firmware danach per USB. Vorher schaltet das Skript das Gerät
    in den ROM-Bootloader: Es sendet 'B' auf der seriellen Leitung, wie die Web-Oberfläche.
    Ein Gerät im Setup-Modus wechselt sofort, ein schlafendes nach einem Druck auf Reset.

.PARAMETER Port
    Serieller Port für den Upload. Standard: COM10.

.PARAMETER Clean
    Löscht vor dem Build die Build-Ausgabe von epd13. Heruntergeladene Bibliotheken bleiben erhalten.

.PARAMETER VerifyOnly
    Baut nicht, sondern prüft nur das vorhandene App-Image. Mit -Upload wird dieses Image ohne
    Neubau geflasht, etwa für mehrere Geräte nacheinander. Nicht mit -Clean kombinierbar.

.PARAMETER UploadBaud
    Baudrate für den Upload. Standard: 2000000, am 17.11.2026 mit der CP2102N-Brücke des
    13,3-Zoll-Geräts stabil getestet. Bei Abbrüchen mit anderer Brücke, langem Kabel oder
    USB-Hub -UploadBaud 921600 verwenden.

.PARAMETER Monitor
    Mit -Upload: öffnet nach erfolgreichem Upload den seriellen Monitor mit Exception-Decoder.
    Danach Reset drücken; die Startausgabe der neuen Firmware ist dann vollständig zu sehen.
    Beenden mit Strg+C.

.PARAMETER NoAutoBootloader
    Sendet kein 'B'. Das Gerät muss dann bereits von Hand in den ROM-Bootloader gebracht sein.

.PARAMETER BootloaderTimeout
    Wartezeit in Sekunden, bis das Gerät im ROM-Bootloader sein muss. Standard: 60.

.PARAMETER KeepLogs
    Anzahl der aufbewahrten Logdateien unter .pio\logs. Standard: 20.

.PARAMETER WhatIf
    Mit -Upload: baut, prüft Image und Port und zeigt, was geschrieben würde. Das Gerät wird
    weder angesprochen noch beschrieben.

.EXAMPLE
    .\build.ps1
    Baut und prüft die Firmware, ohne ein Gerät zu beschreiben.

.EXAMPLE
    .\build.ps1 -Upload -Port COM11 -Verbose
    Baut, prüft und flasht auf COM11 mit ausführlicher PlatformIO-Ausgabe.

.EXAMPLE
    .\build.ps1 -Upload -Monitor
    Baut, prüft, flasht und öffnet danach den seriellen Monitor.

.EXAMPLE
    .\build.ps1 -VerifyOnly -Upload
    Flasht das vorhandene, geprüfte Image ohne Neubau.

.EXAMPLE
    .\build.ps1 -Upload -WhatIf
    Baut, prüft Image und Port und zeigt den Upload, ohne das Gerät anzusprechen.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$Upload,
    [ValidatePattern('^COM\d+$')]
    [string]$Port = 'COM10',
    [switch]$Clean,
    [switch]$VerifyOnly,
    [switch]$NoAutoBootloader,
    [ValidateRange(5, 600)]
    [int]$BootloaderTimeout = 60,
    [ValidateRange(1, 500)]
    [int]$KeepLogs = 20,
    [ValidateSet(115200, 230400, 460800, 921600, 1500000, 2000000)]
    [int]$UploadBaud = 2000000,
    [switch]$Monitor
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# Exitcodes nativer Programme wertet das Skript selbst aus (relevant ab PowerShell 7.3).
$PSNativeCommandUseErrorActionPreference = $false

# --- Feste Vorgaben für das 13,3-Zoll-Display ---------------------------------
$EnvName            = 'epd13'
$ExpectedFlag       = '-DEPD_TYPE_13INCH'
$ForbiddenFlag      = '-DEPD_TYPE_7INCH'
$ExpectedBoard      = 'esp32-c6-devkitm-1'
$ExpectedPartitions = 'part.csv'
$ExpectedChipId     = 13                                    # ESP32-C6 im Image-Header (Offset 12)
$AppDescMagic       = [Convert]::ToUInt32('ABCD5432', 16)   # esp_app_desc_t (Offset 32)
$MinImageSize       = 64KB
$LowSpacePercent    = 5
$MinFreeDiskBytes   = 2GB
$NetworkRetryDelay  = 15
$TargetUsbIds       = 'VID_10C4&PID_EA60|VID_303A'          # CP210x-Brücke oder ESP32-USB-Serial/JTAG

$ProjectRoot  = $PSScriptRoot
$ArtifactPath = Join-Path $ProjectRoot (".pio\build\{0}\firmware.bin" -f $EnvName)
$VerboseRun   = $VerbosePreference -ne 'SilentlyContinue'
$SerialBaud   = 115200
$Invocation   = (@($PSBoundParameters.GetEnumerator() | ForEach-Object {
    if ($_.Value -is [System.Management.Automation.SwitchParameter]) { '-' + $_.Key } else { '-{0} {1}' -f $_.Key, $_.Value }
}) -join ' ')

# --- Laufzeitzustand --------------------------------------------------------------
$script:LogWriter            = $null
$script:LogPath              = $null
$script:LockStream           = $null
$script:LockPath             = $null
$script:CoreDir              = $null
$script:PioPath              = $null
$script:Warnings             = New-Object System.Collections.Generic.List[string]
$script:Phases               = New-Object System.Collections.Generic.List[object]
$script:CurrentPhase         = $null
$script:StepIndex            = 0
$script:StepTotal            = 0
$script:Facts                = [ordered]@{}
$script:SavedEnv             = @{}
$script:SavedConsoleEncoding = $null
$script:FailureMessage       = $null
$script:FailureHints         = @()
$script:Finished             = $false
$script:ExitCode             = 1

# --- Bekannte Fehlerbilder und Hinweise -------------------------------------------
$NetworkPattern = 'HTTPClientError|ConnectionError|ConnectTimeout|ReadTimeout|Max retries exceeded|getaddrinfo failed|NameResolutionError|Could not resolve host|Failed to establish a new connection|RemoteDisconnected|SSLError|CERTIFICATE_VERIFY_FAILED'

$KnownProblems = @(
    [pscustomobject]@{ Phase = 'Build'; Pattern = $NetworkPattern; Hints = @(
        'Netzwerkproblem beim Laden von Plattform, Werkzeugen oder Bibliotheken. Internetzugang, Proxy und Firewall prüfen und den Build erneut starten.') }
    [pscustomobject]@{ Phase = 'Build'; Pattern = "'git' is not recognized|git: command not found|Please install Git|No such file or directory: 'git'"; Hints = @(
        'Git fehlt. GxEPD2 und SerialFlash werden per Git geladen: Git installieren, VS Code neu starten und den Build wiederholen.') }
    [pscustomobject]@{ Phase = 'Build'; Pattern = 'will not fit in region|overflowed by|is greater than maximum allowed'; Hints = @(
        'Die Firmware passt nicht in die App-Partition (app0/app1 laut part.csv). Code oder Bibliotheken verkleinern. Die Partitionstabelle nicht ändern: spiffs mit den Gerätezertifikaten liegt fest bei 0x3B0000.') }
    [pscustomobject]@{ Phase = 'Build'; Pattern = 'fatal error: [^\r\n]*: No such file or directory'; Hints = @(
        'Eine Header-Datei fehlt. Meist ist eine Bibliothek unvollständig geladen: mit -Clean wiederholen. Hilft das nicht, den Ordner .pio\libdeps\epd13 löschen und neu bauen.') }
    [pscustomobject]@{ Phase = 'Build'; Pattern = 'undefined reference to'; Hints = @(
        'Linkerfehler. Mit -Clean wiederholen. Bleibt der Fehler, fehlt Code oder eine Bibliothek in der Konfiguration.') }
    [pscustomobject]@{ Phase = 'Build'; Pattern = 'UnknownPackageError|PackageException|Could not find the package|MissingPackageManifestError|PackageManifestError'; Hints = @(
        'Ein PlatformIO-Paket ist nicht auflösbar oder beschädigt. Netzwerk prüfen. Bei beschädigtem Paket den betroffenen Ordner unter %USERPROFILE%\.platformio\packages oder .pio\libdeps\epd13 löschen und neu bauen.') }
    [pscustomobject]@{ Phase = 'Upload'; Pattern = 'Failed to connect|No serial data received|Wrong boot mode detected|Timed out waiting for packet|Invalid head of packet'; Hints = @(
        'Das Gerät antwortet nicht als ROM-Bootloader. Kleinen Knopf unter der Holzabdeckung gedrückt halten, großen Reset-Knopf kurz drücken, kleinen Knopf loslassen und den Upload sofort neu starten.',
        'Bei wiederholten Abbrüchen ein anderes USB-Datenkabel verwenden und das Gerät direkt statt über einen USB-Hub anschließen.') }
    [pscustomobject]@{ Phase = 'Upload'; Pattern = 'PermissionError|Zugriff verweigert|Access is denied'; Hints = @(
        'Der Port ist von einem anderen Programm belegt. Seriellen Monitor in VS Code oder PlatformIO, die Web-Oberfläche und andere Terminalprogramme schließen.') }
    [pscustomobject]@{ Phase = 'Upload'; Pattern = 'FileNotFoundError|cannot find the file specified|kann die angegebene Datei nicht finden'; Hints = @(
        'Der Port existiert nicht (mehr). USB-Verbindung prüfen und den richtigen Port mit -Port angeben.') }
    [pscustomobject]@{ Phase = 'Upload'; Pattern = 'does not match|Verify failed'; Hints = @(
        'Die Verifikation der geschriebenen Daten ist fehlgeschlagen. Upload wiederholen und ein anderes USB-Kabel verwenden.') }
    [pscustomobject]@{ Phase = 'Alle'; Pattern = '\[Errno 13\] Permission denied|WinError 5\]|WinError 32|being used by another process|von einem anderen Prozess verwendet'; Hints = @(
        'Eine Datei ist gesperrt. Parallele Builds, die IntelliSense-Indexierung von PlatformIO oder einen Virenscanner prüfen. Für den Virenscanner ggf. Ausnahmen für den Projektordner und %USERPROFILE%\.platformio einrichten.') }
    [pscustomobject]@{ Phase = 'Alle'; Pattern = 'No space left on device|not enough space on the disk|nicht genügend Speicherplatz'; Hints = @(
        'Der Datenträger ist voll. Speicher freigeben und den Build wiederholen.') }
    [pscustomobject]@{ Phase = 'Alle'; Pattern = 'UnicodeEncodeError|UnicodeDecodeError'; Hints = @(
        'Zeichensatzfehler in einem Python-Werkzeug. Projekt- und Benutzerpfade ohne Umlaute verwenden.') }
)

# --- Ausgabe und Protokoll ----------------------------------------------------------
function Write-Log {
    param(
        [Parameter(Mandatory, Position = 0)]
        [ValidateSet('STEP', 'INFO', 'OK', 'WARN', 'ERROR', 'HINT', 'CMD', 'OUT', 'EXCERPT')]
        [string]$Level,
        [Parameter(Mandatory, Position = 1)]
        [AllowEmptyString()]
        [string]$Message,
        [switch]$NoConsole
    )
    if ($Level -eq 'WARN') { $script:Warnings.Add($Message) }
    if ($null -ne $script:LogWriter) {
        try {
            $script:LogWriter.WriteLine(('{0:yyyy-MM-dd HH:mm:ss} [{1}] {2}' -f (Get-Date), $Level, $Message))
        } catch {
            $script:LogWriter = $null
            Write-Host "    [WARNUNG] Logdatei nicht mehr beschreibbar: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
    if ($NoConsole) { return }
    switch ($Level) {
        'STEP'    { Write-Host ''; Write-Host ('==> ' + $Message) -ForegroundColor Cyan }
        'INFO'    { Write-Host ('    ' + $Message) }
        'OK'      { Write-Host ('    [OK] ' + $Message) -ForegroundColor Green }
        'WARN'    { Write-Host ('    [WARNUNG] ' + $Message) -ForegroundColor Yellow }
        'ERROR'   { Write-Host ('    [FEHLER] ' + $Message) -ForegroundColor Red }
        'HINT'    { Write-Host ('    [HINWEIS] ' + $Message) -ForegroundColor Cyan }
        'CMD'     { Write-Host ('    > ' + $Message) -ForegroundColor DarkGray }
        'EXCERPT' { Write-Host ('      | ' + $Message) -ForegroundColor Red }
        default   { Write-Host $Message }
    }
}

function Stop-Build {
    param(
        [Parameter(Mandatory, Position = 0)][int]$ExitCode,
        [Parameter(Mandatory, Position = 1)][string]$Message,
        [Parameter(Position = 2)][string[]]$Hints = @()
    )
    $exception = New-Object System.InvalidOperationException $Message
    $exception.Data['BuildExitCode'] = $ExitCode
    $exception.Data['BuildHints'] = @($Hints | Where-Object { $_ })
    throw $exception
}

function Format-Size([long]$Bytes) {
    if ([Math]::Abs($Bytes) -ge 1GB) { return '{0:N1} GB' -f ($Bytes / 1GB) }
    if ([Math]::Abs($Bytes) -ge 1MB) { return '{0:N2} MB' -f ($Bytes / 1MB) }
    if ([Math]::Abs($Bytes) -ge 1KB) { return '{0:N1} KB' -f ($Bytes / 1KB) }
    return '{0} Bytes' -f $Bytes
}

function Format-Duration([TimeSpan]$Span) {
    if ($Span.TotalMinutes -ge 1) { return '{0} min {1:00} s' -f [int][Math]::Floor($Span.TotalMinutes), $Span.Seconds }
    return '{0:N1} s' -f $Span.TotalSeconds
}

function Start-Phase([string]$Name) {
    $script:StepIndex++
    $phase = [pscustomobject]@{
        Name            = $Name
        Status          = 'läuft'
        Stopwatch       = [System.Diagnostics.Stopwatch]::StartNew()
        WarningsAtStart = $script:Warnings.Count
    }
    $script:Phases.Add($phase)
    $script:CurrentPhase = $phase
    Write-Log STEP ('[{0}/{1}] {2}' -f $script:StepIndex, $script:StepTotal, $Name)
}

function Complete-Phase([string]$Status = 'OK') {
    $phase = $script:CurrentPhase
    if ($null -eq $phase) { return }
    $phase.Stopwatch.Stop()
    if ($Status -eq 'OK' -and $script:Warnings.Count -gt $phase.WarningsAtStart) { $Status = 'WARNUNG' }
    $phase.Status = $Status
    $script:CurrentPhase = $null
    Write-Log INFO ('Phase "{0}": {1} nach {2}' -f $phase.Name, $Status, (Format-Duration $phase.Stopwatch.Elapsed)) -NoConsole
}

function Set-ProcessEnv([string]$Name, [string]$Value) {
    if (-not $script:SavedEnv.ContainsKey($Name)) {
        $script:SavedEnv[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process')
    }
    [Environment]::SetEnvironmentVariable($Name, $Value, 'Process')
}

function Initialize-Runtime {
    # Python-Werkzeuge (PlatformIO, esptool) schreiben bei umgeleiteter Ausgabe sonst
    # cp1252 und brechen an Baumzeichen oder Umlauten mit UnicodeEncodeError ab.
    Set-ProcessEnv 'PYTHONUTF8' '1'
    Set-ProcessEnv 'PYTHONIOENCODING' 'utf-8'
    Set-ProcessEnv 'PYTHONUNBUFFERED' '1'
    Set-ProcessEnv 'PLATFORMIO_DISABLE_COLOR' 'true'
    Set-ProcessEnv 'PLATFORMIO_DISABLE_PROGRESSBAR' 'true'
    try {
        $script:SavedConsoleEncoding = [Console]::OutputEncoding
        [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
    } catch {
        $script:SavedConsoleEncoding = $null
    }
}

function Restore-Runtime {
    foreach ($name in @($script:SavedEnv.Keys)) {
        [Environment]::SetEnvironmentVariable($name, $script:SavedEnv[$name], 'Process')
    }
    if ($null -ne $script:SavedConsoleEncoding) {
        try { [Console]::OutputEncoding = $script:SavedConsoleEncoding } catch { }
    }
}

function Initialize-LockAndLog {
    $pioDir = Join-Path $ProjectRoot '.pio'
    $logDir = Join-Path $pioDir 'logs'
    try {
        if (-not (Test-Path -LiteralPath $logDir -PathType Container)) {
            New-Item -ItemType Directory -Path $logDir -Force -Verbose:$false -WhatIf:$false | Out-Null
        }
    } catch {
        Write-Log WARN "Verzeichnis $logDir nicht anlegbar ($($_.Exception.Message)). Es wird ohne Logdatei und Sperre fortgefahren."
        return
    }

    $lockPath = Join-Path $pioDir ('build-{0}.lock' -f $EnvName)
    try {
        $script:LockStream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        $script:LockPath = $lockPath
    } catch {
        Write-Log INFO "Sperre nicht erhalten: $($_.Exception.Message)" -NoConsole
        Stop-Build 2 "Ein anderer Lauf von build.ps1 für $EnvName ist noch aktiv." @(
            'Den anderen Lauf abwarten oder beenden.',
            "Bleibt die Meldung ohne laufenden Build bestehen, die Datei $lockPath löschen.")
    }

    $path = Join-Path $logDir ('build-{0}-{1:yyyyMMdd-HHmmss-fff}.log' -f $EnvName, (Get-Date))
    try {
        $script:LogWriter = [System.IO.StreamWriter]::new($path, $false, (New-Object System.Text.UTF8Encoding $true))
        $script:LogWriter.AutoFlush = $true
        $script:LogPath = $path
    } catch {
        Write-Log WARN "Logdatei nicht anlegbar ($($_.Exception.Message)). Es wird ohne Logdatei fortgefahren."
    }

    try {
        Get-ChildItem -LiteralPath $logDir -Filter ('build-{0}-*.log' -f $EnvName) -File |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -Skip $KeepLogs |
            Remove-Item -Force -ErrorAction SilentlyContinue -Verbose:$false -WhatIf:$false
    } catch {
        Write-Log WARN "Alte Logdateien konnten nicht aufgeräumt werden: $($_.Exception.Message)"
    }
}

# --- Externe Programme ------------------------------------------------------------
function Invoke-Native {
    param(
        [Parameter(Mandatory, Position = 0)][string]$FilePath,
        [Parameter(Position = 1)][string[]]$ArgumentList = @(),
        [switch]$Quiet
    )
    $showOutput = (-not $Quiet) -or $VerboseRun
    $shownArgs = @($ArgumentList | ForEach-Object { if ($_ -match '\s') { '"{0}"' -f $_ } else { $_ } }) -join ' '
    Write-Log CMD ('{0} {1}' -f [System.IO.Path]::GetFileName($FilePath), $shownArgs) -NoConsole:(-not $showOutput)

    $lines = New-Object System.Collections.Generic.List[string]
    # stderr-Zeilen sind in PowerShell ErrorRecords. Mit 'Stop' würde Windows PowerShell 5.1
    # bei der ersten Warnung eines Werkzeugs abbrechen. Entscheidend ist der Exitcode.
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $FilePath @ArgumentList 2>&1 | ForEach-Object {
            $line = ([string]$_).TrimEnd()
            $lines.Add($line)
            Write-Log OUT $line -NoConsole:(-not $showOutput)
        }
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    Write-Log INFO ('Exitcode {0}' -f $exitCode) -NoConsole
    return [pscustomobject]@{
        ExitCode = $exitCode
        Lines    = $lines.ToArray()
        Text     = [string]::Join("`n", $lines.ToArray())
    }
}

function Get-ProblemHints([string]$Text, [string]$Phase) {
    $hints = New-Object System.Collections.Generic.List[string]
    foreach ($problem in $KnownProblems) {
        if (($problem.Phase -eq 'Alle' -or $problem.Phase -eq $Phase) -and $Text -match $problem.Pattern) {
            foreach ($hint in $problem.Hints) {
                if (-not $hints.Contains($hint)) { $hints.Add($hint) }
            }
        }
    }
    return , $hints.ToArray()
}

function Show-ErrorExcerpt([string[]]$Lines, [int]$Max = 15) {
    if ($null -eq $Lines -or $Lines.Count -eq 0) { return }
    $pattern = '(?i)(^|[\s:])(fatal error|error)\b[:\s]|undefined reference|A fatal error occurred|\*\*\* \[|Traceback|Exception:'
    $selected = @($Lines | Where-Object { $_.Length -lt 500 -and $_ -match $pattern } | Select-Object -First $Max)
    $title = 'Relevante Fehlerzeilen:'
    if ($selected.Count -eq 0) {
        $selected = @($Lines | Where-Object { $_ } | Select-Object -Last 10)
        $title = 'Letzte Ausgabezeilen:'
    }
    if ($selected.Count -eq 0) { return }
    Write-Log ERROR $title
    foreach ($line in $selected) { Write-Log EXCERPT $line }
}

function Find-PlatformIO([string]$CoreDir) {
    $fromPath = Get-Command -Name 'pio' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($fromPath) { return $fromPath.Source }
    foreach ($name in @('pio.exe', 'platformio.exe')) {
        $candidate = Join-Path $CoreDir ('penv\Scripts\' + $name)
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    Stop-Build 2 'PlatformIO CLI nicht gefunden.' @(
        "Gesucht im PATH und unter $CoreDir\penv\Scripts.",
        'VS-Code-Erweiterung platformio.platformio-ide öffnen und warten, bis sie PlatformIO Core installiert hat, oder PlatformIO Core separat installieren.')
}

function Find-Esptool([string]$Pio) {
    $candidates = @(
        (Join-Path (Split-Path -Parent $Pio) 'esptool.exe'),
        (Join-Path $script:CoreDir 'penv\Scripts\esptool.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    $fromPath = Get-Command -Name 'esptool' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($fromPath) { return $fromPath.Source }
    return $null
}

function Get-Sha256Hex([string]$Path) {
    # Bewusst nicht Get-FileHash: Das Cmdlet liefert unter -WhatIf in Windows PowerShell 5.1 nichts.
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '')
    } finally {
        $stream.Dispose()
        $sha.Dispose()
    }
}

function Get-FreeDiskSpace([string]$Path) {
    try {
        $root = [System.IO.Path]::GetPathRoot($Path)
        if (-not $root) { return $null }
        return (New-Object System.IO.DriveInfo $root).AvailableFreeSpace
    } catch {
        return $null
    }
}

function Get-NewestSourceFile {
    $files = New-Object System.Collections.Generic.List[System.IO.FileInfo]
    foreach ($dir in @('src', 'include', 'lib')) {
        $full = Join-Path $ProjectRoot $dir
        if (Test-Path -LiteralPath $full -PathType Container) {
            foreach ($file in Get-ChildItem -LiteralPath $full -Recurse -File -ErrorAction SilentlyContinue) { $files.Add($file) }
        }
    }
    foreach ($name in @('platformio.ini', 'part.csv', 'set_env.py', '.env')) {
        $full = Join-Path $ProjectRoot $name
        if (Test-Path -LiteralPath $full -PathType Leaf) { $files.Add((Get-Item -LiteralPath $full -Force)) }
    }
    return $files | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
}

function ConvertFrom-PartitionNumber([string]$Value) {
    $text = $Value.Trim()
    if ($text -match '^0x([0-9a-fA-F]+)$') { return [Convert]::ToInt64($Matches[1], 16) }
    if ($text -match '^(\d+)([KkMm]?)$') {
        $number = [long]$Matches[1]
        switch ($Matches[2].ToUpperInvariant()) {
            'K' { return $number * 1KB }
            'M' { return $number * 1MB }
            default { return $number }
        }
    }
    return $null
}

function Read-PartitionTable([string]$Path) {
    $entries = New-Object System.Collections.Generic.List[object]
    foreach ($raw in Get-Content -LiteralPath $Path) {
        $line = ($raw -replace '#.*$', '').Trim()
        if (-not $line) { continue }
        $columns = @($line -split ',' | ForEach-Object { $_.Trim() })
        if ($columns.Count -lt 5) { continue }
        $entries.Add([pscustomobject]@{
            Name    = $columns[0]
            Type    = $columns[1]
            SubType = $columns[2]
            Offset  = ConvertFrom-PartitionNumber $columns[3]
            Size    = ConvertFrom-PartitionNumber $columns[4]
        })
    }
    return , $entries.ToArray()
}

function Get-ConfigSection($Sections, [string]$Name) {
    foreach ($section in $Sections) {
        if ([string]$section[0] -eq $Name) {
            $options = @{}
            foreach ($pair in $section[1]) { $options[[string]$pair[0]] = $pair[1] }
            return $options
        }
    }
    return $null
}

# --- Phasen -------------------------------------------------------------------------
function Test-Environment {
    Write-Log INFO ('PowerShell {0} ({1}) unter {2}' -f $PSVersionTable.PSVersion, $PSVersionTable.PSEdition, [Environment]::OSVersion.VersionString)
    Write-Log INFO "Projektverzeichnis: $ProjectRoot"

    foreach ($relativePath in @('platformio.ini', 'part.csv', 'set_env.py', 'src\main.cpp')) {
        $path = Join-Path $ProjectRoot $relativePath
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            Stop-Build 2 "Erforderliche Projektdatei fehlt: $path" @(
                'build.ps1 muss im Verzeichnis paperlesspaper-firmware-offline liegen und der Checkout muss vollständig sein.')
        }
    }
    Write-Log OK 'Projektdateien vorhanden (platformio.ini, part.csv, set_env.py, src\main.cpp).'
    if ($ProjectRoot -match '[^\x00-\x7F]') {
        Write-Log WARN 'Der Projektpfad enthält Nicht-ASCII-Zeichen. Die ESP32-Toolchain kann daran scheitern.'
    }

    if ($env:PLATFORMIO_CORE_DIR) { $script:CoreDir = $env:PLATFORMIO_CORE_DIR }
    else { $script:CoreDir = Join-Path $env:USERPROFILE '.platformio' }
    if ($script:CoreDir -match '[^\x00-\x7F]') {
        Write-Log WARN "Das PlatformIO-Verzeichnis $($script:CoreDir) enthält Nicht-ASCII-Zeichen. Die ESP32-Toolchain kann daran scheitern."
    }

    $pio = Find-PlatformIO $script:CoreDir
    $version = Invoke-Native $pio @('--version') -Quiet
    if ($version.ExitCode -ne 0) {
        Show-ErrorExcerpt $version.Lines
        Stop-Build 2 ('PlatformIO startet nicht (Exitcode {0}): {1}' -f $version.ExitCode, $pio) @(
            'VS Code mit der PlatformIO-Erweiterung öffnen. Sie repariert eine beschädigte PlatformIO-Core-Installation beim Start.')
    }
    $versionText = [string]($version.Lines | Where-Object { $_ -match 'version' } | Select-Object -First 1)
    Write-Log OK ('{0} ({1})' -f $versionText, $pio)
    $script:Facts['PlatformIO'] = $versionText
    if ($versionText -match 'version (\d+)\.(\d+)') {
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        if ($major -lt 6 -or ($major -eq 6 -and $minor -lt 1)) {
            Write-Log WARN 'PlatformIO Core ist älter als 6.1. Die pioarduino-Plattform erwartet 6.1 oder neuer: pio upgrade ausführen.'
        }
    }

    $git = Get-Command -Name 'git' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $gitLibsInstalled = Test-Path -LiteralPath (Join-Path $ProjectRoot ('.pio\libdeps\{0}\GxEPD2' -f $EnvName))
    if (-not $git) {
        if ($gitLibsInstalled -or $VerifyOnly) {
            Write-Log WARN 'Git nicht gefunden. Die Git-Bibliotheken sind bereits geladen; Aktualisierungen und die Git-Revision sind aber nicht verfügbar.'
        } else {
            Stop-Build 2 'Git nicht gefunden. GxEPD2 und SerialFlash werden per Git geladen.' @(
                'Git installieren, VS Code bzw. das Terminal neu starten und den Build wiederholen.')
        }
    } else {
        Write-Log OK "Git: $($git.Source)"
        if (Test-Path -LiteralPath (Join-Path $ProjectRoot '.git')) {
            $revision = Invoke-Native $git.Source @('-C', $ProjectRoot, 'rev-parse', 'HEAD') -Quiet
            if ($revision.ExitCode -eq 0 -and $revision.Lines.Count -gt 0) {
                $script:Facts['Git-Revision'] = $revision.Lines[0]
                Write-Log OK "Git-Revision: $($revision.Lines[0])"
                $status = Invoke-Native $git.Source @('-C', $ProjectRoot, 'status', '--porcelain') -Quiet
                $tracked = @($status.Lines | Where-Object { $_ -and -not $_.StartsWith('??') })
                $untracked = @($status.Lines | Where-Object { $_.StartsWith('??') })
                if ($tracked.Count -gt 0) {
                    Write-Log WARN ('{0} geänderte versionierte Dateien. Das Image entspricht nicht genau dem Commit (Details im Log).' -f $tracked.Count)
                    foreach ($line in $tracked) { Write-Log INFO "  $line" -NoConsole }
                    $script:Facts['Git-Revision'] += ' (mit lokalen Änderungen)'
                }
                if ($untracked.Count -gt 0) {
                    Write-Log INFO ('{0} nicht versionierte Einträge (Details im Log).' -f $untracked.Count)
                    foreach ($line in $untracked) { Write-Log INFO "  $line" -NoConsole }
                }
            } else {
                Write-Log WARN ('Git-Revision nicht ermittelbar: {0}' -f (($revision.Lines | Select-Object -First 1) -join ''))
            }
        } else {
            Write-Log INFO 'Kein Git-Checkout. Die Revision wird nicht protokolliert.'
        }
    }

    $roots = @(@($ProjectRoot, $script:CoreDir) | ForEach-Object { [System.IO.Path]::GetPathRoot($_) } | Where-Object { $_ } | Select-Object -Unique)
    foreach ($root in $roots) {
        $free = Get-FreeDiskSpace $root
        if ($null -eq $free) {
            Write-Log WARN "Freier Speicher auf $root nicht ermittelbar."
        } elseif ($free -lt $MinFreeDiskBytes) {
            Write-Log WARN ('Nur {0} frei auf {1}. Der erste Build benötigt bis zu {2}.' -f (Format-Size $free), $root, (Format-Size $MinFreeDiskBytes))
        } else {
            Write-Log OK ('{0} frei auf {1}' -f (Format-Size $free), $root)
        }
    }

    if (Test-Path -LiteralPath (Join-Path $ProjectRoot '.env') -PathType Leaf) {
        Write-Log INFO '.env gefunden. Die Einträge werden als Definitionen übernommen, aber nicht protokolliert.'
    } else {
        Write-Log INFO 'Keine .env vorhanden (optional). Die Meldung ".env file not found" von set_env.py ist dann normal.'
    }

    $platformInstalled = Test-Path -LiteralPath (Join-Path $script:CoreDir 'platforms\espressif32')
    $libsInstalled = Test-Path -LiteralPath (Join-Path $ProjectRoot ('.pio\libdeps\{0}' -f $EnvName))
    if (-not $VerifyOnly -and -not ($platformInstalled -and $libsInstalled)) {
        Write-Log INFO 'Erster Build: Plattform, Toolchain und Bibliotheken werden heruntergeladen. Das dauert mehrere Minuten und braucht Internetzugang.'
    }
    return $pio
}

function Test-ProjectConfiguration([string]$Pio) {
    $result = Invoke-Native $Pio @('project', 'config', '-d', $ProjectRoot, '--json-output') -Quiet
    if ($result.ExitCode -ne 0) {
        Show-ErrorExcerpt $result.Lines
        Stop-Build 2 'platformio.ini kann nicht gelesen werden.' (Get-ProblemHints $result.Text 'Build')
    }
    $start = -1
    for ($i = 0; $i -lt $result.Lines.Count; $i++) {
        if ($result.Lines[$i].StartsWith('[')) { $start = $i; break }
    }
    if ($start -lt 0) { Stop-Build 2 'PlatformIO lieferte keine auswertbare Projektkonfiguration.' }
    try {
        $sections = ($result.Lines[$start..($result.Lines.Count - 1)] -join "`n") | ConvertFrom-Json
    } catch {
        Stop-Build 2 "Projektkonfiguration ist kein gültiges JSON: $($_.Exception.Message)"
    }

    $envConfig = Get-ConfigSection $sections ('env:{0}' -f $EnvName)
    if ($null -eq $envConfig) {
        Stop-Build 2 "Die Umgebung [env:$EnvName] fehlt in platformio.ini."
    }
    $flags = @(@($envConfig['build_flags']) | ForEach-Object { ([string]$_) -split '\s+' } | Where-Object { $_ })
    if ($flags -notcontains $ExpectedFlag) {
        Stop-Build 2 "Build-Flag $ExpectedFlag fehlt in [env:$EnvName]. Ohne dieses Flag entsteht keine Firmware für das 13,3-Zoll-Display."
    }
    if ($flags -contains $ForbiddenFlag) {
        Stop-Build 2 "[env:$EnvName] enthält zusätzlich $ForbiddenFlag. Die Displayauswahl ist widersprüchlich."
    }
    Write-Log OK "Umgebung $EnvName mit Build-Flag $ExpectedFlag."

    $board = [string]$envConfig['board']
    if ($board -ne $ExpectedBoard) {
        Stop-Build 2 "Board in [env:$EnvName] ist '$board', erwartet '$ExpectedBoard'."
    }
    Write-Log OK "Board $board (ESP32-C6)."

    $partitionFile = [string]$envConfig['board_build.partitions']
    if ($partitionFile -ne $ExpectedPartitions) {
        Stop-Build 2 "Partitionstabelle in [env:$EnvName] ist '$partitionFile', erwartet '$ExpectedPartitions'."
    }

    $platformSection = Get-ConfigSection $sections 'platformio'
    if ($null -ne $platformSection -and $platformSection.ContainsKey('default_envs')) {
        $defaults = @($platformSection['default_envs']) -join ', '
        if ($defaults -ne $EnvName) {
            Write-Log INFO "default_envs ist '$defaults'. Das Skript gibt -e $EnvName immer ausdrücklich an."
        }
    }

    $partitions = Read-PartitionTable (Join-Path $ProjectRoot $ExpectedPartitions)
    $apps = @($partitions | Where-Object { $_.Type -eq 'app' })
    if ($apps.Count -eq 0) { Stop-Build 2 "$ExpectedPartitions enthält keine App-Partition." }
    foreach ($app in $apps) {
        if ($null -eq $app.Size -or $null -eq $app.Offset) {
            Stop-Build 2 ('Offset oder Größe der Partition {0} in {1} ist nicht lesbar.' -f $app.Name, $ExpectedPartitions)
        }
        Write-Log OK ('Partition {0} ({1}): Offset 0x{2:X}, Größe 0x{3:X} ({4}).' -f $app.Name, $app.SubType, $app.Offset, $app.Size, (Format-Size $app.Size))
    }
    $appSize = [long](($apps | Measure-Object -Property Size -Minimum).Minimum)
    if (@($apps | Select-Object -ExpandProperty Size -Unique).Count -gt 1) {
        Write-Log WARN ('Die App-Partitionen sind unterschiedlich groß. Geprüft wird gegen die kleinste ({0}).' -f (Format-Size $appSize))
    }
    $spiffs = @($partitions | Where-Object { $_.SubType -eq 'spiffs' }) | Select-Object -First 1
    if ($null -ne $spiffs -and $null -ne $spiffs.Offset -and $null -ne $spiffs.Size) {
        Write-Log INFO ('spiffs bei 0x{0:X} ({1}) enthält bei der Cloud-Firmware die Gerätezertifikate. Dieses Skript beschreibt den Bereich nie.' -f $spiffs.Offset, (Format-Size $spiffs.Size))
    }
    return $appSize
}

function Invoke-FirmwareBuild([string]$Pio) {
    $runArgs = @('run', '-d', $ProjectRoot, '-e', $EnvName)
    if ($VerboseRun) { $runArgs += '-v' }

    if ($Clean) {
        Write-Log INFO "Bereinige die Build-Ausgabe von $EnvName."
        $cleanResult = Invoke-Native $Pio ($runArgs + @('-t', 'clean'))
        if ($cleanResult.ExitCode -ne 0) {
            Show-ErrorExcerpt $cleanResult.Lines
            Stop-Build 3 ('Bereinigen fehlgeschlagen (Exitcode {0}).' -f $cleanResult.ExitCode) (Get-ProblemHints $cleanResult.Text 'Build')
        }
        Write-Log OK 'Build-Ausgabe bereinigt.'
    }

    $maxAttempts = 2
    $build = $null
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        if ($attempt -gt 1) { Write-Log INFO "Versuch $attempt von $maxAttempts." }
        $build = Invoke-Native $Pio $runArgs
        if ($build.ExitCode -eq 0) { break }
        if ($attempt -lt $maxAttempts -and $build.Text -match $NetworkPattern) {
            Write-Log WARN "Netzwerkfehler beim Laden von Paketen erkannt. Neuer Versuch in $NetworkRetryDelay Sekunden."
            Start-Sleep -Seconds $NetworkRetryDelay
            continue
        }
        Show-ErrorExcerpt $build.Lines
        Stop-Build 3 ('PlatformIO-Build fehlgeschlagen (Exitcode {0}).' -f $build.ExitCode) (Get-ProblemHints $build.Text 'Build')
    }

    $usage = @($build.Lines | Where-Object { $_ -match '^(RAM|Flash):' } | ForEach-Object { $_ -replace '\s*\[[=\s]*\]\s*', ' ' })
    if ($usage.Count -gt 0) { $script:Facts['Speicher (PlatformIO)'] = $usage -join '; ' }
    $warningCount = @($build.Lines | Where-Object { $_ -match ':\s*warning:' }).Count
    if ($warningCount -gt 0) {
        Write-Log INFO "$warningCount Compiler-Warnungen in neu übersetzten Dateien (Details im Log)."
    }
    Write-Log OK 'Build erfolgreich.'
}

function Test-AppImage([string]$Path, [long]$MaxSize, [string]$Pio, [bool]$BuiltThisRun) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        if ($BuiltThisRun) {
            Stop-Build 4 "Der Build meldete Erfolg, aber das App-Image fehlt: $Path" @('Mit -Clean erneut bauen.')
        }
        Stop-Build 4 "Kein App-Image vorhanden: $Path" @('Zuerst ohne -VerifyOnly bauen.')
    }
    $file = Get-Item -LiteralPath $Path
    Write-Log INFO ('Image: {0} (geändert {1:dd.MM.yyyy HH:mm:ss})' -f $file.FullName, $file.LastWriteTime)
    $script:Facts['Image'] = $file.FullName

    $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
    $size = [long]$bytes.Length
    if ($size -lt $MinImageSize) {
        Stop-Build 4 ('Das App-Image ist zu klein ({0:N0} Bytes, mindestens {1:N0} erwartet).' -f $size, $MinImageSize) @('Mit -Clean erneut bauen.')
    }
    if ($size -gt $MaxSize) {
        Stop-Build 4 ('Das App-Image ist größer als die App-Partition ({0:N0} von {1:N0} Bytes).' -f $size, $MaxSize) (Get-ProblemHints 'will not fit in region' 'Build')
    }

    if ($bytes[0] -ne 0xE9) {
        $kind = ''
        if ($bytes[0] -eq 0x3C -or $bytes[0] -eq 0x7B) { $kind = ' Die Datei enthält Text oder HTML.' }
        elseif ($bytes[0] -eq 0x50 -and $bytes[1] -eq 0x4B) { $kind = ' Die Datei ist ein ZIP-Archiv.' }
        Stop-Build 4 (('Kein ESP32-App-Image: Magic Byte 0x{0:X2} statt 0xE9.' -f $bytes[0]) + $kind) @('Mit -Clean erneut bauen.')
    }
    $segmentCount = [int]$bytes[1]
    if ($segmentCount -lt 1 -or $segmentCount -gt 16) {
        Stop-Build 4 "Ungültige Segmentanzahl im Image-Header: $segmentCount." @('Mit -Clean erneut bauen.')
    }
    Write-Log OK "ESP32-Image-Header gültig (Magic 0xE9, $segmentCount Segmente)."

    $chipId = [BitConverter]::ToUInt16($bytes, 12)
    if ($chipId -ne $ExpectedChipId) {
        Stop-Build 4 ('Das Image ist für einen anderen Chip gebaut (Chip-ID {0}, erwartet {1} = ESP32-C6).' -f $chipId, $ExpectedChipId) @(
            "Board in [env:$EnvName] prüfen: $ExpectedBoard.")
    }
    Write-Log OK "Chip-ID $chipId (ESP32-C6)."

    if ([BitConverter]::ToUInt32($bytes, 32) -ne $AppDescMagic) {
        Stop-Build 4 'Die App-Beschreibung (esp_app_desc_t) fehlt. Das ist vermutlich ein Bootloader-, Komplett- oder Dateisystem-Image statt firmware.bin.'
    }
    Write-Log OK 'App-Beschreibung vorhanden: App-Image, kein Bootloader- oder Komplett-Image.'

    if ($bytes[23] -eq 1) {
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try { $actual = $sha.ComputeHash($bytes, 0, $bytes.Length - 32) } finally { $sha.Dispose() }
        $expected = New-Object byte[] 32
        [Array]::Copy($bytes, $bytes.Length - 32, $expected, 0, 32)
        if ([BitConverter]::ToString($actual) -ne [BitConverter]::ToString($expected)) {
            Stop-Build 4 'Der angehängte SHA-256-Hash stimmt nicht. Das Image ist beschädigt.' @('Mit -Clean erneut bauen.')
        }
        Write-Log OK 'Angehängter SHA-256-Hash stimmt.'
    } else {
        Write-Log WARN 'Das Image enthält keinen angehängten SHA-256-Hash. Die Integrität wird nur über die esptool-Prüfsumme geprüft.'
    }

    $free = $MaxSize - $size
    $usageText = '{0:N0} Bytes, {1:N1} % der App-Partition, {2} frei' -f $size, (100.0 * $size / $MaxSize), (Format-Size $free)
    $script:Facts['Größe'] = $usageText
    if ((100.0 * $free / $MaxSize) -lt $LowSpacePercent) {
        Write-Log WARN "Die App-Partition ist fast voll: $usageText."
    } else {
        Write-Log OK "Größe passt: $usageText."
    }

    $newest = Get-NewestSourceFile
    if ($null -ne $newest -and $newest.LastWriteTimeUtc -gt $file.LastWriteTimeUtc) {
        $relative = $newest.FullName.Substring($ProjectRoot.Length).TrimStart('\')
        if ($BuiltThisRun) {
            Write-Log INFO "$relative ist neuer als das Image. PlatformIO hielt keinen Neubau für nötig, weil sich der Inhalt nicht geändert hat."
        } else {
            Write-Log WARN ('Das Image ist älter als {0} (geändert {1:dd.MM.yyyy HH:mm:ss}). Vor dem Flashen ohne -VerifyOnly bauen.' -f $relative, $newest.LastWriteTime)
        }
    } else {
        Write-Log OK 'Das Image ist neuer als alle Quell- und Konfigurationsdateien.'
    }

    $esptool = Find-Esptool $Pio
    if (-not $esptool) {
        Write-Log WARN 'esptool nicht gefunden. Die Gegenprüfung mit esptool wurde übersprungen.'
    } else {
        $info = Invoke-Native $esptool @('--chip', 'esp32c6', 'image-info', $file.FullName) -Quiet
        if ($info.ExitCode -ne 0 -and $info.Text -match 'No such command|invalid choice') {
            $info = Invoke-Native $esptool @('--chip', 'esp32c6', 'image_info', $file.FullName) -Quiet
        }
        if ($info.ExitCode -ne 0) {
            Show-ErrorExcerpt $info.Lines
            Stop-Build 4 ('esptool kann das Image nicht lesen (Exitcode {0}).' -f $info.ExitCode) @('Mit -Clean erneut bauen.')
        }
        # esptool 5 schreibt z. B. "Checksum: 0x66 (invalid - calculated 0x99)".
        $invalid = @($info.Lines | Where-Object { $_ -match '\(invalid' })
        if ($invalid.Count -gt 0) {
            foreach ($line in $invalid) { Write-Log EXCERPT $line }
            Stop-Build 4 'esptool meldet eine ungültige Prüfsumme oder einen ungültigen Hash.' @('Mit -Clean erneut bauen.')
        }
        $esptoolVersion = [string]($info.Lines | Where-Object { $_ -match '^esptool v' } | Select-Object -First 1)
        Write-Log OK ('esptool bestätigt Prüfsumme und Validierungs-Hash ({0}).' -f $esptoolVersion.Trim())
    }

    $hash = Get-Sha256Hex $file.FullName
    $script:Facts['SHA-256'] = $hash
    Write-Log INFO "SHA-256 der Datei: $hash"
    return [pscustomobject]@{ Path = $file.FullName; Size = $size; Sha256 = $hash }
}

function Get-FlashImages($Image) {
    # Dieselben Dateien und Adressen wie das PlatformIO-Ziel 'upload' für dieses Board
    # (am 17.11.2026 mit 'pio run -t upload -v' ermittelt).
    $buildDir = Split-Path -Parent $ArtifactPath
    $otaData = Join-Path $script:CoreDir 'packages\framework-arduinoespressif32\tools\partitions\boot_app0.bin'
    $entries = @(
        [pscustomobject]@{ Address = '0x0';     Name = 'Bootloader';        Path = (Join-Path $buildDir 'bootloader.bin'); Sha256 = $null }
        [pscustomobject]@{ Address = '0x8000';  Name = 'Partitionstabelle'; Path = (Join-Path $buildDir 'partitions.bin'); Sha256 = $null }
        [pscustomobject]@{ Address = '0xe000';  Name = 'otadata';           Path = $otaData; Sha256 = $null }
        [pscustomobject]@{ Address = '0x10000'; Name = 'App';               Path = $Image.Path; Sha256 = $Image.Sha256 }
    )
    foreach ($entry in $entries) {
        if (-not (Test-Path -LiteralPath $entry.Path -PathType Leaf)) {
            Stop-Build 4 ('{0} fehlt: {1}' -f $entry.Name, $entry.Path) @(
                'Ohne -VerifyOnly bauen.',
                'Fehlt otadata (boot_app0.bin), den Ordner framework-arduinoespressif32 unter %USERPROFILE%\.platformio\packages löschen und neu bauen.')
        }
    }

    $bootloader = [System.IO.File]::ReadAllBytes($entries[0].Path)
    if ($bootloader.Length -lt 64 -or $bootloader[0] -ne 0xE9 -or [BitConverter]::ToUInt16($bootloader, 12) -ne $ExpectedChipId) {
        Stop-Build 4 'bootloader.bin ist kein Bootloader-Image für den ESP32-C6.' @('Mit -Clean erneut bauen.')
    }
    $partitions = [System.IO.File]::ReadAllBytes($entries[1].Path)
    if ($partitions.Length -ne 3072 -or $partitions[0] -ne 0xAA -or $partitions[1] -ne 0x50) {
        Stop-Build 4 'partitions.bin ist keine gültige Partitionstabelle.' @('Mit -Clean erneut bauen.')
    }
    $partCsv = Get-Item -LiteralPath (Join-Path $ProjectRoot $ExpectedPartitions)
    if ((Get-Item -LiteralPath $entries[1].Path).LastWriteTimeUtc -lt $partCsv.LastWriteTimeUtc) {
        Stop-Build 4 "partitions.bin ist älter als $ExpectedPartitions." @('Ohne -VerifyOnly bauen.')
    }
    if ((Get-Item -LiteralPath $entries[2].Path).Length -ne 8192) {
        Stop-Build 4 "boot_app0.bin hat nicht die erwartete Größe von 8192 Bytes: $otaData" @(
            'Den Ordner framework-arduinoespressif32 unter %USERPROFILE%\.platformio\packages löschen und neu bauen.')
    }

    foreach ($entry in $entries) {
        if (-not $entry.Sha256) { $entry.Sha256 = Get-Sha256Hex $entry.Path }
        Write-Log INFO ('{0,-8} {1,-18} {2:N0} Bytes, SHA-256 {3}' -f $entry.Address, $entry.Name, (Get-Item -LiteralPath $entry.Path).Length, $entry.Sha256) -NoConsole
    }
    Write-Log OK 'Bootloader, Partitionstabelle, otadata und App vorhanden und plausibel (Details im Log).'
    return , $entries
}

function Write-PackageVersions([string]$Pio) {
    $list = Invoke-Native $Pio @('pkg', 'list', '-d', $ProjectRoot, '-e', $EnvName) -Quiet
    if ($list.ExitCode -ne 0) {
        Write-Log WARN ('Paketversionen konnten nicht ermittelt werden (Exitcode {0}). Details im Log.' -f $list.ExitCode)
        return
    }
    $clean = @($list.Lines | ForEach-Object { ($_ -replace '^[^A-Za-z]+', '') -replace '\s*\(required:.*$', '' })
    foreach ($line in $clean) {
        if ($line -match '^Platform |^framework-arduinoespressif32 @|^toolchain-|^tool-esptoolpy @') { Write-Log INFO $line }
    }
    $gitLibs = @($list.Lines | Where-Object { $_ -match '\(required: git\+' } |
        ForEach-Object { ($_ -replace '^[^A-Za-z]+', '') -replace '\s*\(required:.*$', '' })
    if ($gitLibs.Count -gt 0) {
        $script:Facts['Git-Bibliotheken'] = $gitLibs -join '; '
        foreach ($line in $gitLibs) { Write-Log INFO "Nicht festgelegte Git-Bibliothek: $line" }
    }
    $packageCount = @($clean | Where-Object { $_ -match ' @ ' }).Count
    Write-Log OK "$packageCount Paket- und Bibliotheksversionen im Log protokolliert."
}

function Test-UploadPort {
    # Nur lesend. Ohne diese Zeile meldet Windows PowerShell 5.1 unter -WhatIf beim
    # automatischen Laden des CIM-Moduls jede Alias-Definition.
    $WhatIfPreference = $false
    $ports = New-Object System.Collections.Generic.List[object]
    $driverProblems = New-Object System.Collections.Generic.List[string]
    $deviceInfoAvailable = $true
    try {
        foreach ($device in @(Get-CimInstance -ClassName Win32_PnPEntity -ErrorAction Stop -Verbose:$false)) {
            $name = [string]$device.Name
            $id = [string]$device.PNPDeviceID
            $healthy = ($device.ConfigManagerErrorCode -eq 0)
            if ($name -match '\((COM\d+)\)') {
                $ports.Add([pscustomobject]@{ Port = $Matches[1]; Name = $name; DeviceId = $id; Ok = $healthy })
            }
            if (-not $healthy -and ($id -match $TargetUsbIds -or $name -match 'CP210')) {
                $driverProblems.Add(('{0} (Fehlercode {1})' -f $name, $device.ConfigManagerErrorCode))
            }
        }
    } catch {
        $deviceInfoAvailable = $false
        Write-Log WARN "Geräteliste nicht abrufbar ($($_.Exception.Message)). Es werden nur Portnamen geprüft."
        try {
            foreach ($name in [System.IO.Ports.SerialPort]::GetPortNames()) {
                $ports.Add([pscustomobject]@{ Port = $name; Name = '(Gerätetyp unbekannt)'; DeviceId = ''; Ok = $true })
            }
        } catch {
            Write-Log WARN "Portnamen nicht abrufbar: $($_.Exception.Message)"
        }
    }

    $sorted = @($ports | Sort-Object { [int]($_.Port -replace '\D', '') })
    if ($sorted.Count -eq 0) { Write-Log INFO 'Keine seriellen Ports gefunden.' }
    foreach ($entry in $sorted) { Write-Log INFO ('Gefunden: {0,-6} {1}' -f $entry.Port, $entry.Name) }
    foreach ($problem in $driverProblems) { Write-Log WARN "USB-UART-Gerät ohne funktionierenden Treiber: $problem" }

    $target = $sorted | Where-Object { $_.Port -eq $Port } | Select-Object -First 1
    if ($null -eq $target) {
        $available = (@($sorted | ForEach-Object { $_.Port }) -join ', ')
        if (-not $available) { $available = 'keine' }
        $hints = @()
        if ($driverProblems.Count -gt 0) { $hints += 'Den Silicon Labs CP210x USB-to-UART-Treiber installieren und das Gerät neu anstecken.' }
        $hints += 'USB-Datenkabel prüfen. Reine Ladekabel übertragen keine Daten.'
        $hints += 'Den Port des Bilderrahmens mit -Port angeben, zum Beispiel -Port COM11.'
        Stop-Build 5 "Port $Port nicht gefunden. Verfügbare Ports: $available." $hints
    }
    if ($deviceInfoAvailable) {
        if ($target.DeviceId -notmatch $TargetUsbIds) {
            Stop-Build 5 "$Port gehört nicht zum Zielgerät: $($target.Name). Erwartet wird eine CP210x-USB-UART-Brücke." @(
                'Den Port des Bilderrahmens mit -Port angeben.')
        }
        if (-not $target.Ok) {
            Stop-Build 5 "$Port meldet ein Treiberproblem: $($target.Name)." @(
                'Den Silicon Labs CP210x USB-to-UART-Treiber installieren und das Gerät neu anstecken.')
        }
        Write-Log OK "$Port ist $($target.Name)."
        $others = @($sorted | Where-Object { $_.Port -ne $Port -and $_.DeviceId -match $TargetUsbIds })
        if ($others.Count -gt 0) {
            Write-Log WARN ('Weitere mögliche Zielgeräte angeschlossen: {0}. Sicherstellen, dass {1} das gewünschte Gerät ist.' -f (($others | ForEach-Object { $_.Port }) -join ', '), $Port)
        }
    } else {
        Write-Log WARN "Gerätetyp von $Port nicht prüfbar. Sicherstellen, dass dort der Bilderrahmen angeschlossen ist."
    }
}

function Get-BootloaderState([string]$SerialLog) {
    # ROM-Ausgabe des ESP32-C6 nach Neustart in den Download-Modus:
    #   rst:0x.. boot:0x.. (DOWNLOAD(USB/UART0/SDIO_FEI_FEO))  /  waiting for download
    if ($SerialLog -match 'waiting for download|DOWNLOAD\(|ROM Download Bootloader') { return 'Bootloader' }
    if ($SerialLog -match "Bootloader command 'B' received") { return 'CommandReceived' }
    if ($SerialLog -match '\[MAIN\] INIT Device V:') { return 'FirmwareStarted' }
    if ($SerialLog -match '\[MAIN\] test mode check') { return 'FirmwareStarting' }
    return 'Unknown'
}

function Test-RomBootloader([string]$Esptool) {
    # Nur lesend: esptool verbindet sich ohne Reset und liest die MAC-Adresse.
    $probe = Invoke-Native $Esptool @('--chip', 'esp32c6', '--port', $Port, '--baud', "$SerialBaud",
        '--before', 'no-reset', '--after', 'no-reset', '--connect-attempts', '1', 'read-mac') -Quiet
    if ($probe.ExitCode -eq 0) { return $true }
    $hints = Get-ProblemHints $probe.Text 'Upload'
    if ($probe.Text -match 'PermissionError|Zugriff verweigert|Access is denied') {
        Stop-Build 5 "$Port ist von einem anderen Programm belegt." $hints
    }
    return $false
}

function Request-RomBootloader([string]$Esptool) {
    if ($Esptool) {
        Write-Log INFO 'Prüfe, ob das Gerät bereits im ROM-Bootloader ist.'
        if (Test-RomBootloader $Esptool) {
            Write-Log OK 'Das Gerät ist bereits im ROM-Bootloader.'
            return
        }
    } else {
        Write-Log WARN 'esptool nicht gefunden. Der Bootloader-Zustand wird nur über die serielle Ausgabe erkannt.'
    }

    Write-Log INFO ("Sende 'B' an {0}, damit die Firmware in den ROM-Bootloader neu startet (bis {1} s)." -f $Port, $BootloaderTimeout)
    $serial = New-Object System.IO.Ports.SerialPort $Port, $SerialBaud, ([System.IO.Ports.Parity]::None), 8, ([System.IO.Ports.StopBits]::One)
    $serial.DtrEnable = $false
    $serial.RtsEnable = $false
    $serial.ReadTimeout = 50
    $serial.WriteTimeout = 200
    $serial.Encoding = [System.Text.Encoding]::UTF8
    try {
        $serial.Open()
    } catch {
        $reason = $_.Exception.Message
        Write-Log INFO "Port nicht zu öffnen: $reason" -NoConsole
        if ($reason -match 'denied|verweigert|in use|belegt') {
            Stop-Build 5 "$Port ist von einem anderen Programm belegt." @(
                'Seriellen Monitor in VS Code oder PlatformIO, die Web-Oberfläche und andere Terminalprogramme schließen.')
        }
        Stop-Build 5 "$Port lässt sich nicht öffnen: $reason" @(
            'USB-Verbindung prüfen und das Gerät neu anstecken.')
    }

    $serialLog = ''
    $pendingLine = ''
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    $resetHintShown = $false
    $firmwareSeenAt = $null
    $unsupportedShown = $false
    $commandSeen = $false
    $state = 'Unknown'
    try {
        while ($clock.Elapsed.TotalSeconds -lt $BootloaderTimeout) {
            try { $serial.Write('B') } catch { }   # Während des Neustarts kann Schreiben kurz scheitern.
            Start-Sleep -Milliseconds 100
            $chunk = ''
            try { $chunk = $serial.ReadExisting() } catch { $chunk = '' }
            if ($chunk) {
                $serialLog += $chunk
                if ($serialLog.Length -gt 20000) { $serialLog = $serialLog.Substring($serialLog.Length - 20000) }
                $parts = ($pendingLine + $chunk) -split "\r?\n"
                $pendingLine = $parts[-1]
                # Nur vollständige Zeilen protokollieren (0..-1 wäre in PowerShell nicht leer).
                for ($i = 0; $i -lt $parts.Count - 1; $i++) {
                    if ($parts[$i].Trim()) { Write-Log OUT ('[seriell] ' + $parts[$i].TrimEnd()) -NoConsole:(-not $VerboseRun) }
                }
            }

            $state = Get-BootloaderState $serialLog
            if ($state -eq 'Bootloader') { break }
            if ($state -eq 'CommandReceived' -and -not $commandSeen) {
                $commandSeen = $true
                Write-Log OK "Die Firmware hat 'B' empfangen und startet in den ROM-Bootloader neu."
            }
            if ($state -eq 'FirmwareStarted' -and $null -eq $firmwareSeenAt) { $firmwareSeenAt = $clock.Elapsed }
            if (-not $resetHintShown -and $clock.Elapsed.TotalSeconds -ge 4) {
                $resetHintShown = $true
                Write-Log HINT 'Keine Reaktion. Jetzt den großen Reset-Knopf einmal kurz drücken, das Skript sendet weiter.'
            }
            if (-not $unsupportedShown -and $null -ne $firmwareSeenAt -and ($clock.Elapsed - $firmwareSeenAt).TotalSeconds -gt 8) {
                $unsupportedShown = $true
                Write-Log WARN "Die Firmware ist gestartet, reagiert aber nicht auf 'B'. Vermutlich kennt sie das Kommando nicht oder das Gerät erkennt keine USB-Versorgung."
                Write-Log HINT 'Von Hand: kleinen Knopf unter der Holzabdeckung halten, Reset kurz drücken, kleinen Knopf loslassen. Das Skript wartet weiter.'
            }
        }
    } finally {
        try { $serial.Close() } catch { }
        $serial.Dispose()
    }
    if ($pendingLine.Trim()) { Write-Log OUT ('[seriell] ' + $pendingLine.TrimEnd()) -NoConsole:(-not $VerboseRun) }

    if ($state -eq 'Bootloader') {
        Write-Log OK ('Das Gerät ist nach {0} im ROM-Bootloader.' -f (Format-Duration $clock.Elapsed))
        return
    }
    # Ein von Hand in den Bootloader gebrachtes Gerät gibt keinen Text mehr aus; daher erneut fragen.
    if ($Esptool -and (Test-RomBootloader $Esptool)) {
        Write-Log OK 'Das Gerät ist im ROM-Bootloader.'
        return
    }
    $hints = @()
    if ($serialLog.Trim().Length -eq 0) {
        $hints += 'Vom Gerät kam keine serielle Ausgabe. USB-Datenkabel prüfen und Reset drücken, während das Skript wartet.'
    }
    $hints += 'Von Hand: kleinen Knopf unter der Holzabdeckung halten, großen Reset-Knopf kurz drücken, kleinen Knopf loslassen. Danach mit -NoAutoBootloader erneut starten.'
    $hints += 'Mehr Zeit geben: -BootloaderTimeout 120.'
    Stop-Build 7 ('Das Gerät ist nach {0} s nicht im ROM-Bootloader.' -f $BootloaderTimeout) $hints
}

function Invoke-FirmwareUpload {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory, Position = 0)][string]$Pio,
        [Parameter(Mandatory, Position = 1)]$Image
    )
    $script:Facts['Upload'] = "$Port, nicht gestartet (Portprüfung)"
    Test-UploadPort

    $esptool = Find-Esptool $Pio
    if (-not $esptool) {
        Stop-Build 2 'esptool nicht gefunden. Der Upload braucht esptool aus PlatformIO.' @(
            'Einmal ohne -Upload bauen, damit PlatformIO tool-esptoolpy installiert.')
    }
    $images = Get-FlashImages $Image

    $regions = 'Bootloader (0x0), Partitionstabelle (0x8000), otadata (0xE000) und App (0x10000)'
    Write-Log INFO "Geschrieben werden $regions mit $UploadBaud Baud. spiffs mit den Zertifikaten bleibt unberührt."
    if (-not $PSCmdlet.ShouldProcess("$Port, $regions", 'Firmware flashen')) {
        $script:Facts['Upload'] = "$Port, nur simuliert (-WhatIf), Gerät nicht angesprochen"
        Write-Log OK 'Simulation beendet. Ohne -WhatIf würde jetzt der Bootloader angefordert und geflasht.'
        return
    }

    $script:Facts['Upload'] = "$Port, nicht gestartet (Bootloader)"
    if ($NoAutoBootloader) {
        Write-Log HINT 'Ohne automatischen Bootloader-Wechsel: Das Gerät muss bereits im ROM-Bootloader sein.'
    } else {
        Request-RomBootloader $esptool
    }

    # Während des Wartens auf den Bootloader könnte ein anderer Prozess neu gebaut haben.
    foreach ($entry in $images) {
        if ((Get-Sha256Hex $entry.Path) -ne $entry.Sha256) {
            Stop-Build 4 ('{0} wurde seit der Prüfung verändert: {1}' -f $entry.Name, $entry.Path) @(
                'Parallele Builds beenden und das Skript erneut starten.')
        }
    }
    $script:Facts['Upload'] = "$Port, fehlgeschlagen"

    # Direkt mit esptool statt 'pio run -t upload': kein zweiter PlatformIO-Lauf, kein Neubau,
    # und es werden genau die geprüften Dateien geschrieben. 'keep' übernimmt Flash-Modus,
    # -Frequenz und -Größe aus den Image-Headern, die Bytes bleiben unverändert.
    $uploadArgs = @('--chip', 'esp32c6', '--port', $Port, '--baud', "$UploadBaud",
        '--before', 'no-reset', '--after', 'hard-reset',
        'write-flash', '--compress', '--flash-mode', 'keep', '--flash-freq', 'keep', '--flash-size', 'keep')
    foreach ($entry in $images) { $uploadArgs += @($entry.Address, $entry.Path) }
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    $result = Invoke-Native $esptool $uploadArgs
    if ($result.ExitCode -ne 0) {
        Show-ErrorExcerpt $result.Lines
        $hints = @(Get-ProblemHints $result.Text 'Upload')
        if ($UploadBaud -gt 921600) {
            $hints += "Mit -UploadBaud $UploadBaud kann die USB-Brücke oder das Kabel überfordert sein. Mit -UploadBaud 921600 wiederholen."
        }
        Stop-Build 6 ('Upload auf {0} fehlgeschlagen (Exitcode {1}).' -f $Port, $result.ExitCode) $hints
    }

    $verified = @($result.Lines | Where-Object { $_ -match 'Hash of data verified' }).Count
    if ($verified -ge $images.Count) {
        Write-Log OK "esptool hat alle $verified geschriebenen Bereiche per Hash verifiziert."
    } else {
        Write-Log WARN ('esptool hat nur {0} von {1} Bereichen per Hash bestätigt. Die Upload-Ausgabe im Log prüfen.' -f $verified, $images.Count)
    }

    $script:Facts['Upload'] = ('{0}, erfolgreich ({1} Baud, {2})' -f $Port, $UploadBaud, (Format-Duration $clock.Elapsed))
    Write-Log OK "Upload auf $Port erfolgreich."
    if ($Monitor) {
        Write-Log HINT 'Der serielle Monitor öffnet nach der Zusammenfassung. Sobald er läuft, den großen Reset-Knopf drücken.'
    } else {
        Write-Log HINT 'Das Board hat keinen automatischen Reset. Jetzt den großen Reset-Knopf drücken, damit die neue Firmware startet.'
        Write-Log HINT "Kontrolle: 'pio device monitor -p $Port -b 115200' zeigt beim Start '[MAIN] test mode check...'. Beim nächsten Upload öffnet -Monitor den Monitor automatisch."
    }
}

function Write-Summary {
    Write-Log STEP 'Zusammenfassung'
    foreach ($phase in $script:Phases) {
        Write-Log INFO ('{0,-34} {1,-12} {2}' -f $phase.Name, $phase.Status, (Format-Duration $phase.Stopwatch.Elapsed))
    }
    Write-Log INFO ''
    foreach ($key in $script:Facts.Keys) {
        Write-Log INFO ('{0,-22} {1}' -f ($key + ':'), $script:Facts[$key])
    }
    if ($script:Warnings.Count -gt 0) {
        Write-Log INFO ''
        Write-Log INFO ('Warnungen ({0}):' -f $script:Warnings.Count)
        foreach ($warning in @($script:Warnings)) { Write-Log INFO "  - $warning" }
    }
    if ($script:LogPath) {
        Write-Log INFO ''
        Write-Log INFO "Log: $($script:LogPath)"
    }
    Write-Log INFO ''
    if ($script:ExitCode -eq 0) {
        Write-Log OK 'ERGEBNIS: Erfolg.'
    } else {
        Write-Log ERROR $script:FailureMessage
        foreach ($hint in $script:FailureHints) { Write-Log HINT $hint }
        Write-Log ERROR ('ERGEBNIS: fehlgeschlagen (Exitcode {0}).' -f $script:ExitCode)
    }
}

# --- Hauptablauf ----------------------------------------------------------------------
$locationPushed = $false
try {
    Push-Location -LiteralPath $ProjectRoot
    $locationPushed = $true
    Initialize-Runtime
    Initialize-LockAndLog

    if ($VerifyOnly -and $Upload) { $script:StepTotal = 4 } elseif ($VerifyOnly) { $script:StepTotal = 3 } elseif ($Upload) { $script:StepTotal = 6 } else { $script:StepTotal = 5 }
    if ($VerifyOnly -and $Upload -and $WhatIfPreference) { $mode = "vorhandenes Image prüfen, Upload auf $Port ohne Neubau nur simulieren (-WhatIf)" }
    elseif ($VerifyOnly -and $Upload) { $mode = "vorhandenes Image prüfen und ohne Neubau auf $Port flashen" }
    elseif ($VerifyOnly) { $mode = 'nur vorhandenes Image prüfen, nichts bauen oder flashen' }
    elseif ($Upload -and $WhatIfPreference) { $mode = "bauen, prüfen und Upload auf $Port nur simulieren (-WhatIf)" }
    elseif ($Upload) { $mode = "bauen, prüfen und auf $Port flashen" }
    else { $mode = 'bauen und prüfen, kein Upload' }

    Write-Log STEP 'paperlesspaper-Firmware für das 13,3-Zoll-Display (PlatformIO-Umgebung epd13)'
    Write-Log INFO "Modus: $mode"
    Write-Log INFO ('Aufruf: build.ps1 {0}' -f $Invocation).TrimEnd()
    Write-Log INFO ('Start: {0:dd.MM.yyyy HH:mm:ss}' -f (Get-Date))
    if ($script:LogPath) { Write-Log INFO "Log: $($script:LogPath)" }

    if ($VerifyOnly -and $Clean) {
        Stop-Build 2 '-VerifyOnly lässt sich nicht mit -Clean kombinieren.' @(
            '-Clean löscht das Image, das -VerifyOnly prüfen soll.')
    }
    if ($Monitor -and -not $Upload) {
        Stop-Build 2 '-Monitor wirkt nur zusammen mit -Upload.' @(
            "Ohne Upload den Monitor direkt starten: pio device monitor -p $Port -b $SerialBaud")
    }

    Start-Phase 'Umgebung prüfen'
    $pio = Test-Environment
    $script:PioPath = $pio
    Complete-Phase

    Start-Phase 'Projektkonfiguration prüfen'
    $appSize = Test-ProjectConfiguration $pio
    Complete-Phase

    if (-not $VerifyOnly) {
        Start-Phase 'Firmware bauen'
        Invoke-FirmwareBuild $pio
        Complete-Phase
    }

    Start-Phase 'App-Image prüfen'
    $image = Test-AppImage -Path $ArtifactPath -MaxSize $appSize -Pio $pio -BuiltThisRun (-not $VerifyOnly)
    Complete-Phase

    if (-not $VerifyOnly) {
        Start-Phase 'Paketversionen protokollieren'
        Write-PackageVersions $pio
        Complete-Phase
    }

    if ($Upload) {
        Start-Phase "Firmware auf $Port übertragen"
        Invoke-FirmwareUpload $pio $image
        Complete-Phase
    } elseif (-not $VerifyOnly) {
        $script:Facts['Upload'] = 'nicht angefordert, kein Gerät beschrieben'
    }

    $script:ExitCode = 0
    $script:Finished = $true
} catch {
    $failure = $_
    $code = $null
    try { $code = $failure.Exception.Data['BuildExitCode'] } catch { $code = $null }
    if ($null -eq $code) {
        $script:ExitCode = 1
        $script:FailureMessage = 'Unerwarteter Fehler im Skript: ' + $failure.Exception.Message
        Write-Log ERROR $script:FailureMessage
        Write-Log INFO $failure.InvocationInfo.PositionMessage
        Write-Log INFO $failure.ScriptStackTrace -NoConsole
    } else {
        $script:ExitCode = [int]$code
        $script:FailureMessage = $failure.Exception.Message
        $script:FailureHints = @($failure.Exception.Data['BuildHints'])
    }
    if (-not $VerboseRun -and $script:ExitCode -in 3, 6) {
        $script:FailureHints += 'Für ausführliche PlatformIO-Ausgabe mit -Verbose erneut starten.'
    }
    Complete-Phase 'FEHLER'
    $script:Finished = $true
} finally {
    if ($script:Finished) {
        try { Write-Summary } catch { Write-Host "Zusammenfassung nicht darstellbar: $($_.Exception.Message)" -ForegroundColor Red }
    } else {
        Complete-Phase 'ABGEBROCHEN'
        Write-Log WARN 'Lauf abgebrochen. Das Ergebnis ist unvollständig; das App-Image nicht verwenden.'
    }
    Restore-Runtime
    if ($null -ne $script:LockStream) {
        $script:LockStream.Dispose()
        if ($script:LockPath) { Remove-Item -LiteralPath $script:LockPath -Force -ErrorAction SilentlyContinue -WhatIf:$false }
    }
    if ($null -ne $script:LogWriter) { $script:LogWriter.Dispose() }
    if ($locationPushed) { Pop-Location }
}

# Erst nach Zusammenfassung, Freigabe der Sperre und Schließen des Logs: Der Monitor läuft,
# bis er mit Strg+C beendet wird, und belegt den Port.
if ($Monitor -and $Upload -and $script:ExitCode -eq 0 -and -not $WhatIfPreference -and $script:PioPath) {
    Write-Host ''
    Write-Host "Serieller Monitor auf $Port. Jetzt den großen Reset-Knopf drücken. Beenden mit Strg+C." -ForegroundColor Cyan
    & $script:PioPath device monitor -d $ProjectRoot -e $EnvName -p $Port -b $SerialBaud -f esp32_exception_decoder
}
exit $script:ExitCode

#Requires -Version 5.1
param([switch]$Demo, [switch]$Console, [switch]$InstallOnly)
$ErrorActionPreference = 'Stop'
$desktopDirectory = $PSScriptRoot
$environmentDirectory = Join-Path $desktopDirectory '.venv'
$pythonPath = Join-Path $environmentDirectory 'Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $basePython = $null
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        $candidate = & py.exe -3 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0) { $basePython = $candidate | Select-Object -Last 1 }
    }
    if (-not $basePython) {
        $candidate = Join-Path $env:USERPROFILE '.platformio/penv/Scripts/python.exe'
        if (Test-Path -LiteralPath $candidate) { $basePython = $candidate }
    }
    if (-not $basePython) { throw 'Python 3.10 or newer is required. Install Python from python.org.' }
    Write-Host 'Creating the local Python environment...'
    & $basePython -m venv $environmentDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Creating the Python environment failed.' }
}
& $pythonPath -c "import importlib.util, sys; sys.exit(0 if sys.version_info >= (3, 10) and importlib.util.find_spec('PySide6') and importlib.util.find_spec('serial') else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Installing GUI dependencies into desktop/.venv...'
    & $pythonPath -m pip install --disable-pip-version-check -r (Join-Path $desktopDirectory 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Installing the GUI dependencies failed.' }
}
if ($InstallOnly) { exit 0 }
$launchArguments = @((Join-Path $desktopDirectory 'run.py'))
if ($Demo) { $launchArguments += '--demo' }
if ($Console) {
    & $pythonPath @launchArguments
    exit $LASTEXITCODE
}
$pythonWindowPath = Join-Path $environmentDirectory 'Scripts/pythonw.exe'
# Quote the script path for Start-Process, including workspace paths with spaces.
$quotedArguments = @($launchArguments | ForEach-Object { '"' + $_ + '"' })
Start-Process -FilePath $pythonWindowPath -ArgumentList $quotedArguments -WorkingDirectory $desktopDirectory -WindowStyle Hidden

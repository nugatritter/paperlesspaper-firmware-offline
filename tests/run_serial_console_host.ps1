$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$outputDirectory = Join-Path $projectDirectory '.pio/serial-console-host'
$jsonDirectory = Join-Path $projectDirectory '.pio/libdeps/epd13/ArduinoJson/src'
if (-not (Test-Path -LiteralPath $jsonDirectory)) {
    throw 'Build epd13 first to install ArduinoJson.'
}
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
$executable = Join-Path $outputDirectory 'serial_console_host.exe'
& g++ -std=c++17 -Wall -Wextra -Werror "-I$projectDirectory/src" "-I$jsonDirectory" (Join-Path $PSScriptRoot 'serial_console_host.cpp') -o $executable
if ($LASTEXITCODE -ne 0) { throw 'Host compilation failed.' }
& $executable
if ($LASTEXITCODE -ne 0) { throw 'Host tests failed.' }

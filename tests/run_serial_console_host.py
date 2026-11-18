"""Compile and run the serial console host tests on Windows, Linux and macOS."""
from pathlib import Path
import os
import shutil
import subprocess
import sys

project = Path(__file__).resolve().parents[1]
json_directory = project / ".pio/libdeps/epd13/ArduinoJson/src"
if not json_directory.is_dir():
    raise SystemExit("Build epd13 first to install ArduinoJson: pio run -e epd13")

compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++") or shutil.which("c++")
if not compiler:
    raise SystemExit("A host C++17 compiler (g++ or clang++) is required, or set CXX.")

build_directory = project / ".pio/serial-console-host"
build_directory.mkdir(parents=True, exist_ok=True)
executable = build_directory / ("serial_console_host" + (".exe" if os.name == "nt" else ""))
compile_command = [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                   f"-I{project / 'src'}", f"-I{json_directory}",
                   str(project / "tests/serial_console_host.cpp"), "-o", str(executable)]
if subprocess.run(compile_command).returncode:
    sys.exit("Host compilation failed.")
if subprocess.run([str(executable)]).returncode:
    sys.exit("Host tests failed.")

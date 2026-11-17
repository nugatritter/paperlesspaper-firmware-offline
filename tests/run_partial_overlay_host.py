"""Compile the production region code against simulated SPI, flash, and display APIs."""
from pathlib import Path
import shutil
import subprocess

project = Path(__file__).resolve().parents[1]
compiler = shutil.which("g++")
if not compiler:
    raise SystemExit("A host g++ compiler is required.")

source = (project / "src/epaper_partial_13.cpp").read_text(encoding="utf-8")
source = source.replace('#include "epaper_partial_13.h"', "")
source = source.replace('#include "epaper_display.h"', "")
harness = (project / "tests/partial_overlay_host.cpp").read_text(encoding="utf-8")
build_directory = project / ".pio/partial-overlay-host"
build_directory.mkdir(parents=True, exist_ok=True)
translation_unit = build_directory / "partial_overlay_host.cpp"
translation_unit.write_text(harness.replace("// PRODUCTION_SOURCE", source), encoding="utf-8")
executable = build_directory / "partial_overlay_host.exe"
subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-DEPD_TYPE_13INCH",
                str(translation_unit), "-o", str(executable)], check=True)
subprocess.run([str(executable)], check=True)

main_source = (project / "src/main.cpp").read_text(encoding="utf-8")
function_start = main_source.index("int showStoredImage(")
body_start = main_source.index("{", function_start)
brace_depth = 1
function_end = body_start + 1
while brace_depth:
    brace_depth += (main_source[function_end] == "{") - (main_source[function_end] == "}")
    function_end += 1
presentation_function = main_source[function_start:function_end]
presentation_harness = (project / "tests/presentation_recovery_host.cpp").read_text(encoding="utf-8")
translation_unit = build_directory / "presentation_recovery_host.cpp"
translation_unit.write_text(presentation_harness.replace("// PRODUCTION_SOURCE", presentation_function), encoding="utf-8")
for panel in ("epd13", "epd7"):
    executable = build_directory / f"presentation_recovery_{panel}.exe"
    defines = ["-DEPD_TYPE_13INCH"] if panel == "epd13" else []
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", *defines,
                    str(translation_unit), "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True)

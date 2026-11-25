"""Compile the production region code against simulated SPI, flash, and display APIs."""
from pathlib import Path
import os
import shutil
import subprocess

project = Path(__file__).resolve().parents[1]
compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++") or shutil.which("c++")
if not compiler:
    raise SystemExit("A host C++17 compiler (g++ or clang++) is required, or set CXX.")

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
                f"-I{project / 'src'}",
                str(translation_unit), "-o", str(executable)], check=True)
subprocess.run([str(executable)], check=True)

main_source = (project / "src/main.cpp").read_text(encoding="utf-8")
function_start = main_source.index("static void loadRenderJournal()")
function_end = main_source.index("static int showImageError(", function_start)
progress_start = main_source.index("constexpr int QUARTER_PROGRESS_ADDRESS")
progress_end = main_source.index("int StartCounter", progress_start)
storage_source = main_source[progress_start:progress_end]
download_start = main_source.index("int processHttpDownload() {")
download_end = main_source.index("void initFirstBoot(", download_start)
for name, functions in (("presentation_recovery", main_source[function_start:function_end]),
                        ("quarter_download", main_source[download_start:download_end])):
    harness = (project / f"tests/{name}_host.cpp").read_text(encoding="utf-8")
    translation_unit = build_directory / f"{name}_host.cpp"
    translation_unit.write_text(harness.replace("// PRODUCTION_SOURCE", storage_source + functions), encoding="utf-8")
    for panel in ("epd13", "epd7"):
        executable = build_directory / f"{name}_{panel}.exe"
        defines = ["-DEPD_TYPE_13INCH"] if panel == "epd13" else []
        if name == "quarter_download":
            defines.append("-DPANEL_EMERGENCY_CONFIG")
        subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", *defines,
                        f"-I{project / 'src'}", str(translation_unit), "-o", str(executable)], check=True)
        subprocess.run([str(executable)], check=True)

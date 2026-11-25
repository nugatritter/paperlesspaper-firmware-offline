"""Simulate removal of USB during driver power-on, immediately before the physical refresh."""
import os
from pathlib import Path
import shutil
import subprocess

project = Path(__file__).resolve().parents[1]
drivers = project / ".pio/build/epd13/usb-guarded"
compiler = os.environ.get("CXX") or shutil.which("c++")
if not compiler or not drivers.is_dir():
    raise SystemExit("Build epd13 first and install a host C++ compiler.")


def function(source, signature):
    start = source.index(signature)
    return source[start:source.index("\n}", start) + 2]


harness = """
#include <cassert>
#include <cstdint>
#define HIGH 1
#define LOW 0
#define OUTPUT 1
void delay(int) {}
void pinMode(int, int) {}
void digitalWrite(int, int) {}
bool connected = true;
bool losePower = false;
bool refreshDenied = false;
bool usbCheckConnect() { return connected; }
struct { void println(const char *) {} } Serial;
enum class CsType { CS_NONE = 0, CS_MASTER = 1, CS_SLAVE = 2, CS_MASTER_SLAVE = 3 };
CsType operator|(CsType a, CsType b) { return CsType(int(a) | int(b)); }
struct Driver {
    int commands = 0, shutdowns = 0, _paging_step = 0, _epd_quick_stop_time = 1, _rst = 1, full_refresh_time = 1;
    bool _suspend_refresh = false, _epd_quick = false;
    void _PowerOn() { if (losePower) connected = false; }
    void _powerOn() { _PowerOn(); }
    void powerOff() { shutdowns++; }
    void _waitWhileBusy(const char * = nullptr, int = 0) {}
    void _clearPartialRamArea(CsType) {}
    void _setPartialRamArea(int, int, int, int, CsType) {}
    void _writeCommand(int cmd) { assert(cmd == 0x12); commands++; }
    void _writeData(int) {}
    void _drf(CsType) { commands++; }
    void refresh(bool);
    void refresh(int16_t, int16_t, int16_t, int16_t);
};
"""
harness += function((project/"src/epaper_display.cpp").read_text(), "bool allowPanelRefreshCommand()")
exercise = """
int main() {
    for (int window = 0; window < 2; ++window) {
        for (int scenario = 0; scenario < 3; ++scenario) {
            Driver driver;
            connected = scenario != 0;
            losePower = scenario == 1;
            refreshDenied = false;
            if (window) driver.refresh(32, 32, 64, 64);
            else driver.refresh(false);
            assert(driver.commands == (scenario == 2));
            assert(driver.shutdowns == (scenario != 2));
            assert(refreshDenied == (scenario != 2));
        }
    }
}
"""
directory = project/".pio/partial-overlay-host"
directory.mkdir(parents=True, exist_ok=True)
for model in ("GxEPD2_1330c_EL133UF3", "GxEPD2_730c_GDEP073E01"):
    driver = (drivers/f"{model}.cpp").read_text()
    methods = [function(driver, f"void {model}::refresh({signature}") for signature in ("bool", "int16_t")]
    source = directory/f"{model}_power.cpp"
    source.write_text(harness + "\n" + "\n".join(methods).replace(model+"::", "Driver::") + exercise)
    executable = source.with_suffix(".exe")
    subprocess.run([compiler, "-std=c++17", str(source), "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
    print(f"PASS {model}: full and paged refreshes, USB present, absent and lost during power-on")

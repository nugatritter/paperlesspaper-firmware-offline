"""Insert a live USB check at the two selected drivers' hardware refresh commands."""
from hashlib import sha256
from pathlib import Path

Import("env")


REVIEWED_DRIVERS = {
    "GxEPD2_1330c_EL133UF3": "b0aa0e5c374568dae2cff484c88ea228fe89ec59ff4b817ea95a661fc2c4a7ed",
    "GxEPD2_730c_GDEP073E01": "6bd67a75ca58b1f4c97b390c8080f1f97b2fe30bf97dbf1472ca8a895a73c24d",
}


def guard_display_driver(build_env, node):
    original = Path(node.srcnode().get_abspath())
    source = original.read_text()
    if sha256(source.encode()).hexdigest() != REVIEWED_DRIVERS[original.stem]:
        raise ValueError(f"Review refresh commands in updated {original.name}")
    header = original.with_suffix(".h")
    source = source.replace(f'#include "{header.name}"', f'#include "{header.as_posix()}"')
    if original.stem == "GxEPD2_1330c_EL133UF3":
        commands = {"_drf(CsType::CS_MASTER_SLAVE);": 1, "_drf(refresh_cs);": 1}
    else:
        commands = {"_writeCommand(0x12);  // Display Refresh": 2}
    for command, expected in commands.items():
        if source.count(command) != expected:
            raise ValueError(f"Review USB refresh guards for updated {original.name}")
        source = source.replace(command, "if (!allowPanelRefreshCommand()) { powerOff(); return; }\n   " + command)
    output = Path(build_env.subst("$BUILD_DIR")) / "usb-guarded" / original.name
    output.parent.mkdir(parents=True, exist_ok=True)
    source = "extern bool allowPanelRefreshCommand();\n" + source
    if not output.exists() or output.read_text() != source:
        output.write_text(source)
    return build_env.File(str(output))


for driver in REVIEWED_DRIVERS:
    env.AddBuildMiddleware(guard_display_driver, f"*/epd7c/{driver}.cpp")

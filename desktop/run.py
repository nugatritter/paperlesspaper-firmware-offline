"""Launch Panel Studio; --demo never opens a serial port."""
import argparse
import os
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="eYellowBoard Panel Studio")
    parser.add_argument("--demo", action="store_true", help="Show synthetic data without connecting to hardware")
    parser.add_argument("--preview", type=Path, help="Render all pages as PNG files in this directory, without hardware")
    arguments = parser.parse_args()
    if arguments.preview:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    try:
        from PySide6.QtCore import QSettings, QTimer
        from panel_studio.app import MainWindow, create_application
    except ImportError as error:
        print(f"Missing dependency: {error}\nInstall: python -m pip install -r requirements.txt", file=sys.stderr)
        return 1
    application = create_application()
    preferences = None
    if arguments.preview:
        arguments.preview.mkdir(parents=True, exist_ok=True)
        preferences = QSettings(str(arguments.preview / "preferences.ini"), QSettings.Format.IniFormat)
    window = MainWindow(demo=arguments.demo or bool(arguments.preview), preferences=preferences)
    window.show()
    if arguments.preview:
        def capture():
            for index, name in enumerate(("overview", "settings", "firmware", "console")):
                window.select_page(index)
                application.processEvents()
                if not window.grab().save(str(arguments.preview / f"{name}.png")):
                    raise RuntimeError("Could not save preview image")
            window.close()
        QTimer.singleShot(300, capture)
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())

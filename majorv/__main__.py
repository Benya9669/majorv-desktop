import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from .controller import Panel
from .desktop import Desktop
from .individual import IndividualProfile
from .version import VERSION


def main():
    parser = argparse.ArgumentParser(description="Панель управления Marshall Major V")
    parser.add_argument("--demo", action="store_true", help="запустить с виртуальными наушниками")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setOrganizationName("Major V Desktop")
    app.setApplicationName("Major V Desktop")
    app.setApplicationVersion(VERSION)
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("assets") / "majorv.png")))
    QQuickStyle.setStyle("Basic")
    panel = Panel(demo=args.demo)
    individual = IndividualProfile(demo=args.demo)
    desktop = Desktop(panel, VERSION)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("panel", panel)
    engine.rootContext().setContextProperty("individualProfile", individual)
    engine.rootContext().setContextProperty("desktop", desktop)
    try:
        engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name("qml") / "Main.qml")))
        if not engine.rootObjects():
            return 1
        desktop.attach(engine.rootObjects()[0])
        if args.demo and os.environ.get("MAJORV_SMOKE_TEST") == "1":
            # Let the packaged launcher render its first frame, then exit cleanly for CI.
            QTimer.singleShot(500, desktop.quit)
        return app.exec()
    finally:
        desktop.close()
        individual.close()
        panel.close()
        del engine


if __name__ == "__main__":
    sys.exit(main())

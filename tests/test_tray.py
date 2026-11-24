import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QIcon, QWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from majorv.controller import Panel
from majorv.desktop import Desktop


ROOT = Path(__file__).resolve().parents[1]


def wait_until(predicate, milliseconds=3000):
    deadline = time.monotonic() + milliseconds / 1000
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    return predicate()


def exercise_windows_tray():
    app = QApplication([])
    app.setWindowIcon(QIcon(str(ROOT / "majorv/assets/majorv.png")))
    app.setQuitOnLastWindowClosed(False)
    window = QWindow()
    panel = Panel(demo=True)
    with tempfile.TemporaryDirectory() as temp:
        settings = QSettings(str(Path(temp) / "tray.ini"), QSettings.Format.IniFormat)
        desktop = Desktop(panel, "test", settings)
        desktop.attach(window)
        menu = desktop._menu
        presets = desktop._presets

        def open_and_hover():
            desktop._tray.activated.emit(QSystemTrayIcon.ActivationReason.Context)
            assert wait_until(menu.isVisible), "tray menu did not open"
            handle = menu.windowHandle()
            QTest.mouseMove(handle, menu.actionGeometry(menu.actions()[0]).center())
            QTest.mouseMove(handle, menu.actionGeometry(presets.menuAction()).center())

        try:
            assert desktop._tray.contextMenu() is None, "Windows is exporting the native submenu"
            panel.scan()
            assert wait_until(lambda: bool(panel.selectedAddress))
            panel.connectDevice()
            assert wait_until(lambda: panel.phase == "connected")
            for preset in ("bass", "individual", "marshall"):
                open_and_hover()
                assert wait_until(presets.isVisible), "preset submenu did not open"
                action = desktop._actions[preset]
                QTest.mouseClick(presets.windowHandle(), Qt.MouseButton.LeftButton,
                                 pos=presets.actionGeometry(action).center())
                assert wait_until(lambda: panel.eq == preset and panel.phase == "connected")
                assert action.isChecked() and not menu.isVisible()
            panel.disconnectDevice()
            assert wait_until(lambda: panel.phase == "idle")
            open_and_hover()
            assert not presets.menuAction().isEnabled()
            assert not wait_until(presets.isVisible, 500)
            QTest.keyClick(menu.windowHandle(), Qt.Key.Key_Escape)
            assert not menu.isVisible()
        finally:
            desktop.close()
            panel.close()
            window.close()


@unittest.skipUnless(sys.platform == "win32", "Windows tray widget menu")
class TrayTests(unittest.TestCase):
    def test_hover_and_choose_presets_in_demo(self):
        # The rest of the suite may already have a QGuiApplication. Widgets need
        # their own QApplication, and a native plugin crash must fail this test.
        env = os.environ.copy()
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        subprocess.run([sys.executable, "-m", "tests.test_tray"], cwd=ROOT, env=env,
                       check=True, timeout=30)


if __name__ == "__main__":
    exercise_windows_tray()

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QIcon, QWindow
from PySide6.QtQml import QQmlApplicationEngine
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


def exercise_window_close(scenario):
    has_tray = scenario != "without-tray"
    app = QApplication([])
    app.setWindowIcon(QIcon(str(ROOT / "majorv/assets/majorv.png")))
    engine = QQmlApplicationEngine()
    engine.loadData(b"import QtQuick; Window { width: 240; height: 120 }")
    window, = engine.rootObjects()
    panel = Panel(demo=True)
    with tempfile.TemporaryDirectory() as temp, patch.object(
            QSystemTrayIcon, "isSystemTrayAvailable", return_value=has_tray):
        desktop = Desktop(panel, "test", QSettings(str(Path(temp) / "tray.ini"), QSettings.Format.IniFormat))
        desktop.attach(window)
        closed = []
        visible = []

        def restore_and_exit():
            visible.append(window.isVisible())
            desktop._tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
            visible.append(window.isVisible())
            if scenario == "quit-hidden":
                window.close()
                visible.append(window.isVisible())
            next(action for action in desktop._menu.actions() if action.text() == "Выйти").trigger()

        try:
            window.show()
            QTimer.singleShot(0, lambda: closed.append(window.close()))
            if has_tray:
                # A premature lastWindowClosed quit would prevent this timer from running.
                QTimer.singleShot(100, restore_and_exit)
            QTimer.singleShot(3000, lambda: app.exit(1))
            assert app.exec() == 0, "main event loop did not terminate normally"
            assert closed == [not has_tray], "unexpected result of the window close event"
            if has_tray:
                expected = [False, True, False] if scenario == "quit-hidden" else [False, True]
                assert visible == expected, "unexpected window visibility during tray actions"
        finally:
            desktop.close()
            panel.close()
            del engine


def run_scenario(*args):
    # Widgets need a fresh QApplication, and the close tests exercise its actual event loop.
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("QT_QUICK_BACKEND", "software")
    subprocess.run([sys.executable, "-m", "tests.test_tray", *args], cwd=ROOT, env=env,
                   check=True, timeout=30)


class TrayTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows tray widget menu")
    def test_hover_and_choose_presets_in_demo(self):
        run_scenario()

    def test_close_restore_and_quit(self):
        for scenario in ("quit-visible", "quit-hidden"):
            with self.subTest(scenario=scenario):
                run_scenario(scenario)

    def test_close_without_tray_exits(self):
        run_scenario("without-tray")


if __name__ == "__main__":
    if sys.argv[1:]:
        exercise_window_close(sys.argv[1])
    else:
        exercise_windows_tray()

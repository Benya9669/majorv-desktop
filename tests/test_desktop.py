import os
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from majorv.controller import Panel
from majorv.desktop import Desktop
from majorv.individual import IndividualProfile


class DesktopTests(unittest.TestCase):
    def test_demo_controls_loss_and_reconnect(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        panel = Panel(demo=True)
        profile = IndividualProfile(demo=True)
        desktop = Desktop(panel, "0.1.0")
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
        engine.rootContext().setContextProperty("panel", panel)
        engine.rootContext().setContextProperty("individualProfile", profile)
        engine.rootContext().setContextProperty("desktop", desktop)
        qml = Path(__file__).resolve().parents[1] / "majorv/qml/Main.qml"
        engine.load(QUrl.fromLocalFile(str(qml)))
        try:
            window, = engine.rootObjects()

            def control(name):
                return window.findChild(QQuickItem, name)

            def click(name):
                item = control(name)
                self.assertTrue(item.isEnabled(), name)
                pos = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
                QTest.mouseClick(window, Qt.LeftButton, pos=pos.toPoint())

            def wait_until(condition):
                end = time.monotonic() + 5
                while not condition() and time.monotonic() < end:
                    app.processEvents()
                    time.sleep(0.01)
                self.assertTrue(condition(), (panel.phase, panel.error, warnings))

            wait_until(window.isExposed)
            self.assertFalse(control("eqPicker").isEnabled())
            click("scanButton")
            wait_until(lambda: bool(panel.selectedAddress))
            click("connectionButton")
            wait_until(lambda: panel.phase == "connected")
            self.assertEqual(control("batteryLabel").property("text"), "78%")
            click("slotTimerButton")
            click("timerPicker")
            QTest.keyClick(window, Qt.Key_Up)
            QTest.keyClick(window, Qt.Key_Return)
            wait_until(lambda: panel.timerMinutes == "15")
            click("closeSlotTimerButton")
            for name, key, expected in [
                ("eqPicker", "eq", "individual"),
                ("mButtonPicker", "mButton", "spotify"),
                ("promptsPicker", "prompts", "off"),
            ]:
                click(name)
                QTest.keyClick(window, Qt.Key_Down)
                QTest.keyClick(window, Qt.Key_Return)
                wait_until(lambda: getattr(panel, key) == expected)
            click("profileButton")
            wait_until(lambda: len(profile.levels) == 5)
            click("closeProfileButton")
            wait_until(lambda: not profile.levels)
            click("demoLossButton")
            wait_until(lambda: panel.phase == "waiting")
            self.assertIn("потеряна", control("errorMessage").property("text"))
            self.assertEqual(control("batteryLabel").property("text"), "—")
            self.assertFalse(control("eqPicker").isEnabled())
            wait_until(lambda: panel.phase == "connected")
            self.assertEqual(panel.eq, "individual")
            click("connectionButton")
            wait_until(lambda: panel.phase == "idle")
            self.assertEqual(panel.error, "")
            self.assertEqual(warnings, [])
        finally:
            panel.close()
            del engine

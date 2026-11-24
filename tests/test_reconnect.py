import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QSettings

from majorv.backend import DemoBackend
from majorv.controller import Panel


class ReconnectTests(unittest.TestCase):
    def setUp(self):
        self.app = QCoreApplication.instance() or QCoreApplication([])

    def wait_for(self, condition):
        deadline = time.monotonic() + 6
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertTrue(condition())

    def test_resume_choose_other_and_explicit_disconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = QSettings(str(Path(tmp) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("bluetooth/address", DemoBackend.address)
            panel = Panel(demo=True, settings=settings)
            try:
                self.wait_for(lambda: panel.phase == "connected")
                panel.chooseOther()
                self.wait_for(lambda: panel.phase == "idle")
                self.assertFalse(settings.contains("bluetooth/address"))
                self.assertEqual(panel.selectedAddress, DemoBackend.address)
                panel.connectDevice()
                self.wait_for(lambda: panel.phase == "connected")
                self.assertEqual(settings.value("bluetooth/address"), DemoBackend.address)
                panel.disconnectDevice()
                self.wait_for(lambda: panel.phase == "idle")
                self.assertFalse(panel._retry.isActive())
            finally:
                panel.close()

    def test_waits_for_remembered_address_when_another_pair_is_nearby(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = QSettings(str(Path(tmp) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("bluetooth/address", "DE:00:00:00:00:02")
            panel = Panel(demo=True, settings=settings)
            try:
                self.wait_for(lambda: panel.phase == "seeking")
                self.wait_for(lambda: panel.phase == "waiting")
                self.assertNotEqual(panel.selectedAddress, DemoBackend.address)
                self.assertEqual(panel.battery, -1)
                panel.chooseOther()
                self.wait_for(lambda: panel.phase == "idle")
                self.assertEqual(panel.selectedAddress, DemoBackend.address)
            finally:
                panel.close()

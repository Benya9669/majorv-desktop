import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from PySide6.QtCore import QCoreApplication, QObject, QSettings, Signal
from PySide6.QtNetwork import QNetworkReply

from majorv.desktop import Desktop


class Headphones(QObject):
    changed = Signal()
    demo = False
    phase = "connected"
    selectedAddress = "AA:BB:CC:DD:EE:FF"
    battery = 10


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.app = QCoreApplication.instance() or QCoreApplication([])
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = QSettings(str(Path(self.temp.name) / "prefs.ini"), QSettings.Format.IniFormat)
        self.panel = Headphones()
        self.desktop = Desktop(self.panel, "0.9.2", self.settings)

    def test_low_battery_rearms_after_charge_but_not_reconnection(self):
        key = "desktop/low/" + self.panel.selectedAddress
        self.panel.changed.emit()
        self.assertIn("10%", self.desktop.batteryWarning)
        self.assertTrue(self.settings.value(key, type=bool))
        self.panel.phase = "waiting"
        self.panel.battery = -1
        self.panel.changed.emit()
        self.assertFalse(self.desktop.batteryWarning)
        self.assertTrue(self.settings.value(key, type=bool))
        self.panel.phase = "connected"
        self.panel.battery = 40
        self.panel.changed.emit()
        self.assertFalse(self.settings.contains(key))
        self.desktop.setThreshold(20)
        self.panel.battery = 19
        self.panel.changed.emit()
        self.assertTrue(self.settings.value(key, type=bool))
        self.desktop.setThreshold(0)
        self.assertFalse(self.settings.contains(key))
        self.assertFalse(self.desktop.batteryWarning)

    def test_release_comparison_and_unpublished_version(self):
        reply = Mock()
        reply.attribute.return_value = 200
        reply.error.return_value = QNetworkReply.NetworkError.NoError
        reply.readAll.return_value = b'{"tag_name":"v0.10.0"}'
        self.desktop._release_checked(reply)
        self.assertTrue(self.desktop.newRelease)
        reply.readAll.return_value = b'{"tag_name":"v0.9.2"}'
        self.desktop._release_checked(reply)
        self.assertFalse(self.desktop.newRelease)
        reply.attribute.return_value = 404
        self.desktop._release_checked(reply)
        self.assertIn("релизов", self.desktop.updateStatus)

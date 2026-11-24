import json
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QProcess, QSettings

from majorv.individual import IndividualProfile


class IndividualProfileTests(unittest.TestCase):
    def setUp(self):
        self.app = QCoreApplication.instance() or QCoreApplication([])

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertTrue(predicate())

    def test_named_curve_roundtrip_and_demo_undo(self):
        with tempfile.TemporaryDirectory() as path:
            settings = QSettings(path + "/profiles.ini", QSettings.Format.IniFormat)
            profile = IndividualProfile(demo=True, settings=settings)
            profile.read("")
            profile.edit(0, 100)
            profile.edit(1, 0)
            profile.edit(4, 85)
            mixed = [6.0, -6.0, 0.0, 0.0, 4.2]
            self.assertEqual(profile.draft, mixed)
            profile.saveNamed("Музыка / Jazz")
            profile.apply()
            self.assertEqual(profile.levels, mixed)
            profile.undo()
            self.assertEqual(profile.draft, [0.0] * 5)
            profile.apply()
            profile.read("")
            self.assertEqual(profile.levels, [0.0] * 5)
            second = IndividualProfile(demo=True, settings=QSettings(path + "/profiles.ini", QSettings.Format.IniFormat))
            second.read("")
            self.assertEqual(second.profileNames, ["Музыка / Jazz"])
            second.loadNamed("Музыка / Jazz")
            self.assertEqual(second.draft, mixed)
            second.undo()
            self.assertEqual(second.draft, [0.0] * 5)

    def test_applies_all_bands_and_displays_verified_wire_values(self):
        profile = IndividualProfile()
        address = "11:22:33:44:55:66"
        profile._address = address
        profile._levels = [0.0, 0.11, 0, 0, 0]
        profile._draft = profile._levels.copy()
        profile.edit(0, 100)
        profile.edit(2, 51)
        profile.edit(3, 0)
        profile.edit(4, 100)
        self.assertTrue(profile.supported)
        start = QProcess.start

        def start_worker(process, program, arguments):
            args = arguments[arguments.index("apply"):]
            self.assertEqual(args[:3], ["apply", address, "--bands"])
            self.assertEqual(list(map(float, args[3:8])), [6, 0.11, 0.12, -6, 6])
            self.assertEqual(args[8:], ["--expect", "0", "11", "0", "0", "0", "--json"])
            return start(process, program, ["-c", "print('[6, 0.11, 0.11, -6, 6]')"])

        try:
            with patch.object(QProcess, "start", start_worker):
                profile.apply()
                self.wait_for(lambda: not profile.busy)
            self.assertEqual(profile.error, "")
            self.assertFalse(profile.dirty)
            self.assertEqual(profile.levels, [6, 0.11, 0.11, -6, 6])
            profile.undo()
            self.assertEqual(profile.draft, [0, 0.11, 0, 0, 0])
        finally:
            profile.close()

    def test_invalid_gain_cannot_start_a_hardware_save(self):
        profile = IndividualProfile()
        profile._levels = [0.0] * 5
        profile._draft = profile._levels.copy()
        profile._draft[1] = 0.01
        self.assertTrue(profile.dirty)
        self.assertFalse(profile.supported)
        with patch.object(QProcess, "start", side_effect=AssertionError("Unexpected hardware save")):
            profile.apply()

    def test_partial_write_allows_retry_after_fresh_read(self):
        profile = IndividualProfile()
        address = "11:22:33:44:55:66"
        profile._address = address
        profile._levels = [0] * 5
        profile._draft = [-6, 6, 0, -6, 6]
        start = QProcess.start
        replies = iter(["import sys; sys.exit(2)", "print('[-6,6,0,-6,6]')", "print('[-6,6,0,-6,6]')"])

        def start_worker(process, program, args):
            return start(process, program, ["-c", next(replies)])

        try:
            with patch.object(QProcess, "start", start_worker):
                profile.apply()
                self.wait_for(lambda: not profile.busy)
                self.assertIn("не подтверждено", profile.error)
                self.assertFalse(profile.needsApply)
                profile.read(address)
                self.wait_for(lambda: not profile.busy)
                self.assertFalse(profile.dirty)
                self.assertTrue(profile.needsApply)
                profile.apply()
                self.wait_for(lambda: not profile.busy)
                self.assertFalse(profile.needsApply)
                self.assertEqual(profile.error, "")
        finally:
            profile.close()

    def test_demo_and_validation_do_not_open_a_socket(self):
        profile = IndividualProfile(demo=True)
        real = IndividualProfile()
        with patch.object(QProcess, "start", side_effect=AssertionError("Unexpected subprocess")):
            profile.discover("DE:00:00:00:00:01")
            self.assertEqual(profile.levels, [0.0] * 5)
            profile.cancel()
            self.assertEqual(profile.levels, [])
            real.read("invalid")
            self.assertTrue(real.error)
            self.assertFalse(real.busy)
            real.cancel()
            self.assertEqual(real.error, "")

    def test_discovery_reads_one_device_and_prompts_for_multiple(self):
        profile = IndividualProfile()
        ble = "CC:22:33:44:55:66"
        first, second = "00:11:22:33:44:55", "00:11:22:33:44:66"
        start = QProcess.start
        reads = []
        names = {first: "Major V"}

        def start_worker(process, program, args):
            if args[-4:] == ["devices", "--ble-address", ble, "--json"]:
                result = names
            else:
                self.assertEqual(args[-3], "read")
                reads.append(args[-2])
                result = [1, 0, 0, 0, 0]
            return start(process, program, ["-c", f"print({json.dumps(result)!r})"])

        try:
            with patch.object(QProcess, "start", start_worker):
                profile.discover(ble)
                self.wait_for(lambda: not profile.busy)
                self.assertEqual(profile.selectedAddress, first)
                self.assertEqual(profile.levels, [1, 0, 0, 0, 0])
                names[second] = "Major V"
                profile.discover(ble)
                self.wait_for(lambda: not profile.busy)
                self.assertEqual(reads, [first])
                self.assertEqual(profile.selectedAddress, "")
                self.assertEqual([d["value"] for d in profile.devices], [first, second])
                profile.read(second)
                self.wait_for(lambda: not profile.busy)
                self.assertEqual(reads, [first, second])
                names.clear()
                profile.discover(ble)
                self.wait_for(lambda: not profile.busy)
                self.assertTrue(profile.error)
                self.assertEqual(profile.levels, [])
                self.assertEqual(profile.devices, [])
        finally:
            profile.close()

    def test_async_result_failure_and_cancelled_read(self):
        profile = IndividualProfile()
        address = "11:22:33:44:55:66"
        start = QProcess.start
        workers = iter([
            "import time; time.sleep(10)",
            "print('[-6, -0.12, 0, 0.12, 6]')",
            "print('[0, 0]')",
        ])

        def start_test_worker(process, program, args):
            self.assertEqual(program, sys.executable)
            self.assertEqual(args[-3:], ["read", address, "--json"])
            return start(process, program, ["-c", next(workers)])

        try:
            with patch.object(QProcess, "start", start_test_worker):
                profile.read(address)
                self.assertTrue(profile.busy)
                self.wait_for(lambda: profile.findChild(QProcess).state() == QProcess.ProcessState.Running)
                profile.read(address)
                self.wait_for(lambda: not profile.busy)
                self.assertEqual(profile.levels, [-6, -0.12, 0, 0.12, 6])
                self.assertEqual(profile.error, "")
                profile.read(address)
                self.assertEqual(profile.levels, [])
                self.wait_for(lambda: not profile.busy)
                self.assertTrue(profile.error)
                self.assertEqual(profile.levels, [])
        finally:
            profile.close()

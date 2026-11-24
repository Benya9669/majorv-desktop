import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from scripts import individual_eq


class AutoAddressTests(unittest.TestCase):
    def run_cli(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("sys.argv", ["individual_eq.py", *args]), redirect_stdout(stdout), redirect_stderr(stderr):
            code = individual_eq.main()
        return code, stdout.getvalue(), stderr.getvalue()

    def test_devices_json_and_auto_read(self):
        candidates = {"11:22:33:44:55:66": "Major V"}
        with patch.object(individual_eq, "discover_devices", return_value=candidates) as discover:
            code, stdout, _ = self.run_cli(["devices", "--json", "--ble-address", "AA:BB:CC:DD:EE:FF"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout), candidates)
            discover.assert_called_once_with("AA:BB:CC:DD:EE:FF", 20)
            with patch.object(individual_eq, "probe", return_value=0) as probe:
                self.assertEqual(self.run_cli(["read", "--json"])[0], 0)
                probe.assert_called_once_with("11:22:33:44:55:66", 20, read_profile=True, json_output=True)

    def test_ambiguous_missing_and_explicit_device(self):
        candidates = {"11:22:33:44:55:66": "Major V", "22:33:44:55:66:77": "Major V"}
        with patch.object(individual_eq, "discover_devices", return_value=candidates) as discover:
            with patch.object(individual_eq, "probe", return_value=0) as probe:
                code, stdout, stderr = self.run_cli(["read", "--json"])
                self.assertEqual(code, 1)
                self.assertEqual(stdout, "")
                self.assertIn("22:33:44:55:66:77", stderr)
                discover.return_value = {}
                self.assertEqual(self.run_cli(["read", "--json"])[0], 1)
                probe.assert_not_called()
                discover.reset_mock()
                self.assertEqual(self.run_cli(["probe", "11:22:33:44:55:66"])[0], 0)
                discover.assert_not_called()
                probe.assert_called_once_with("11:22:33:44:55:66", 20, read_profile=False, json_output=False)

    def test_interactive_selection_by_number(self):
        with patch("sys.stdin", io.StringIO("2\n")), redirect_stderr(io.StringIO()):
            self.assertEqual(individual_eq.select_device({"A": "Major V", "B": "Major V"}, True), "B")

    def test_apply_five_bands_auto_address_and_legacy_form(self):
        address = "11:22:33:44:55:66"
        with patch.object(individual_eq, "discover_devices", return_value={address: "Major V"}), \
             patch.object(individual_eq, "probe", return_value=0) as probe:
            args = ["apply", "--bands", "-6", "6", "0.12", "-6", "6", "--json"]
            self.assertEqual(self.run_cli(args)[0], 0)
            probe.assert_called_with(address, 20, apply_levels=[-6, 6, 0.12, -6, 6], expected=None, json_output=True)
            self.assertEqual(self.run_cli(["apply", address, "0"])[0], 0)
            probe.assert_called_with(address, 20, apply_levels=0, expected=None, json_output=False)
            probe.reset_mock()
            self.assertEqual(self.run_cli(["apply", "--bands", "0", "0.13", "0", "0", "0"])[0], 1)
            probe.assert_not_called()

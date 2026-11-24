import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from majorv.classic import _bluez_candidates, find_classic_devices
from scripts.individual_eq import SERVICE_UUID


class ClassicCandidatesTests(unittest.IsolatedAsyncioTestCase):
    def test_bluez_distinguishes_classic_from_public_ble_and_honors_alias(self):
        def device(address, name, uuids, **kwargs):
            return {"org.bluez.Device1": dict(
                Address=address, Name=name, AddressType="public",
                Paired=True, UUIDs=uuids, **kwargs,
            )}

        classic = "00:11:22:33:44:A1"
        devices = {
            "audio": device(classic.lower(), "MAJOR V", [
                "0000110B-0000-1000-8000-00805F9B34FB",
            ], Alias="My headset"),
            "le": device("00:11:22:33:44:A2", "MAJOR V [LE]", [
                "0000180f-0000-1000-8000-00805f9b34fb",
            ]),
            "other": device("00:11:22:33:44:A3", "MAJOR VI", [SERVICE_UUID]),
            "unpaired": device("00:11:22:33:44:A4", "Major V", [SERVICE_UUID]),
            "blocked": device("00:11:22:33:44:A5", "Major V", [SERVICE_UUID], Blocked=True),
        }
        devices["unpaired"]["org.bluez.Device1"]["Paired"] = False
        self.assertEqual(_bluez_candidates(devices), {classic: "My headset"})

    async def test_linux_ambiguity_and_shared_public_address(self):
        candidates = {"00:11:22:33:44:A1": "Major V", "00:11:22:33:44:A2": "Major V"}
        with patch("majorv.classic.sys.platform", "linux"), patch(
            "majorv.classic._linux_devices", new_callable=AsyncMock, return_value=candidates
        ):
            self.assertEqual(await find_classic_devices("00:11:22:33:44:a2"), {
                "00:11:22:33:44:A2": "Major V"
            })
            self.assertEqual(await find_classic_devices("AA:AA:AA:AA:AA:AA"), candidates)

    @unittest.skipUnless(sys.platform == "win32", "requires PyWinRT")
    async def test_windows_matches_shared_container_or_returns_candidates(self):
        from winrt.system import box_guid, box_string

        container = uuid4()
        first, second = "00:11:22:33:44:A1", "00:11:22:33:44:A2"

        def endpoint(address, group, name):
            return SimpleNamespace(name=name, properties={
                "System.Devices.Aep.DeviceAddress": box_string(address),
                "System.Devices.Aep.ContainerId": box_guid(group),
            })

        devices = [endpoint(first, uuid4(), "Major V"), endpoint(second, container, "Major V")]
        le = "CA:00:00:00:00:01"
        with patch("winrt.windows.devices.enumeration.DeviceInformation") as api, patch(
            "winrt.windows.devices.bluetooth.BluetoothDevice"
        ), patch("winrt.windows.devices.bluetooth.BluetoothLEDevice"):
            api.find_all_async_with_kind_aqs_filter_and_additional_properties = AsyncMock(
                side_effect=[devices, [endpoint(le, container, "Major V [LE]")], devices, []]
            )
            self.assertEqual(await find_classic_devices(le), {second: "Major V"})
            self.assertEqual(await find_classic_devices(le), {first: "Major V", second: "Major V"})

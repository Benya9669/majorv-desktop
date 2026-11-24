import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from bleak.exc import BleakError

from majorv.backend import BleBackend, DemoBackend
from scripts import majorv_client as protocol


class BleSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_device_read_write_and_link_loss(self):
        backend = BleBackend()
        device = SimpleNamespace(name="Paired headset")
        with patch("majorv.backend.BleakScanner.discover", new_callable=AsyncMock) as discover:
            discover.return_value = {
                "A": (device, SimpleNamespace(local_name="Major V")),
                "B": (SimpleNamespace(name="MAJOR V"), SimpleNamespace(local_name=None)),
                "C": (SimpleNamespace(name="Other"), SimpleNamespace(local_name=None)),
            }
            self.assertEqual(await backend.scan(), {"A": "Major V", "B": "MAJOR V"})

        lost = Mock()
        values = {
            protocol.UUID_BATTERY: b"\x00",
            protocol.UUID_EQ_PRESET: b"\x01\x01\x03",
            protocol.UUID_M_BUTTON: b"\x00\x09",
            protocol.UUID_SOUND_PROMPTS: b"\xff\xff",
            protocol.UUID_POWER_TIMER: bytes.fromhex("00 02 03 00 01 08 34 01 02 03 84"),
        }
        with patch("majorv.backend.BleakClient") as factory:
            client = factory.return_value
            client.is_connected = True
            client.connect = AsyncMock()
            client.disconnect = AsyncMock()
            client.read_gatt_char = AsyncMock(side_effect=values.__getitem__)
            client.write_gatt_char = AsyncMock()
            await backend.connect("A", lost)
            self.assertIs(factory.call_args.args[0], device)
            self.assertTrue(factory.call_args.kwargs["pair"])
            first_disconnect = factory.call_args.kwargs["disconnected_callback"]
            self.assertEqual(await backend.read(), {
                "battery": 0, "eq": "mid", "m_button": "spotify", "prompts": "on",
                "timer": "15", "eq_active_slot": None, "eq_slot1": None, "eq_slot2": None,
            })
            for key, value, uuid, expected in [
                ("eq", "individual", protocol.UUID_EQ_PRESET, b"\x01\x01\x01"),
                ("m_button", "eq", protocol.UUID_M_BUTTON, b"\x00\x08"),
                ("prompts", "off", protocol.UUID_SOUND_PROMPTS, b"\x00\x00"),
                ("timer", "20", protocol.UUID_POWER_TIMER, bytes.fromhex("02 00 01 08 34 01 02 04 b0")),
            ]:
                await backend.set_value(key, value)
                client.write_gatt_char.assert_awaited_with(uuid, expected, response=True)
            await backend.disconnect()
            first_disconnect(client)
            lost.assert_not_called()
            await backend.connect("A", lost)
            factory.call_args.kwargs["disconnected_callback"](client)
            lost.assert_called_once()
            with self.assertRaises(ConnectionError):
                await backend.read()

    async def test_partial_read_does_not_substitute_defaults(self):
        backend = BleBackend()
        with patch("majorv.backend.BleakClient") as factory:
            client = factory.return_value
            client.connect = AsyncMock()
            client.is_connected = True
            client.read_gatt_char = AsyncMock(side_effect=[
                b"\xff", b"\x01\x01\x04", BleakError("Unavailable"), b"\x00", b"\x03",
            ])
            await backend.connect("A", Mock())
            self.assertEqual(await backend.read(), {
                "battery": None, "eq": "treble", "m_button": None, "prompts": None,
                "timer": None, "eq_active_slot": None, "eq_slot1": None, "eq_slot2": None,
            })
            client.read_gatt_char.side_effect = BleakError("Access denied")
            with self.assertRaisesRegex(RuntimeError, "Access denied"):
                await backend.read()

    async def test_button_switch_and_selecting_preset_while_slot_one_active(self):
        backend = BleBackend()
        slot_one = bytes.fromhex("ff 02 00 01 01 00 01")
        with patch("majorv.backend.BleakClient") as factory:
            client = factory.return_value
            client.connect = AsyncMock()
            client.is_connected = True
            client.start_notify = AsyncMock()
            await backend.connect("A", Mock())
            updates = Mock()
            await backend.subscribe(updates)
            callback = next(call.args[1] for call in client.start_notify.await_args_list
                            if call.args[0] == protocol.UUID_EQ_PRESET)
            callback(None, slot_one)
            updates.assert_called_with({"eq": "marshall", "eq_active_slot": "1",
                                        "eq_slot1": "marshall", "eq_slot2": "individual"})
            client.read_gatt_char = AsyncMock(side_effect=[slot_one, slot_one[:-1] + b"\x04"])
            client.write_gatt_char = AsyncMock()
            await backend.set_value("eq", "treble")
            self.assertEqual([call.args[1] for call in client.write_gatt_char.await_args_list],
                             [bytes.fromhex("01 01 04"), bytes.fromhex("00 01")])

    async def test_demo_flow_without_radio(self):
        backend = DemoBackend()
        address, = (await backend.scan()).keys()
        lost = Mock()
        await backend.connect(address, lost)
        self.assertEqual((await backend.read())["eq"], "marshall")
        await backend.set_value("eq", "individual")
        with self.assertRaises(ValueError):
            await backend.set_value("eq", "invalid")
        backend.simulate_loss()
        with self.assertRaises(ConnectionError):
            await backend.set_value("eq", "bass")
        await backend.connect(address, lost)
        self.assertEqual((await backend.read())["eq"], "individual")
        await backend.disconnect()
        lost.assert_called_once()

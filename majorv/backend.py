"""Session-based transports for the Major V settings screen."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from scripts import majorv_client as protocol


def battery_percent(raw: bytes | bytearray) -> int | None:
    return raw[0] if len(raw) == 1 and raw[0] <= 100 else None


def timer_minutes(raw: bytes | bytearray) -> str | None:
    if len(raw) != 11 or raw[:5] != b"\x00\x02\x03\x00\x01" or raw[7:9] != b"\x01\x02":
        return None
    seconds = int.from_bytes(raw[-2:], "big")
    return str(seconds // 60) if seconds % 60 == 0 else None


READS = {
    "battery": (protocol.UUID_BATTERY, battery_percent),
    "eq": (protocol.UUID_EQ_PRESET, protocol.eq_preset_name),
    "m_button": (protocol.UUID_M_BUTTON, protocol.decode_m_button),
    "prompts": (protocol.UUID_SOUND_PROMPTS, protocol.decode_sound_prompts),
    "timer": (protocol.UUID_POWER_TIMER, timer_minutes),
}


def decode_field(key, raw):
    if key == "eq":
        return protocol.eq_slots(raw) or {
            "eq": protocol.eq_preset_name(raw), "eq_active_slot": None,
            "eq_slot1": None, "eq_slot2": None,
        }
    return {key: READS[key][1](raw)}


class BleBackend:
    def __init__(self) -> None:
        self._devices: dict[str, BLEDevice] = {}
        self._client: BleakClient | None = None

    async def scan(self) -> dict[str, str]:
        discovered = await BleakScanner.discover(timeout=5.0, return_adv=True)
        self._devices.clear()
        names = {}
        for address, (device, advertisement) in discovered.items():
            name = protocol.matching_name("Major V", advertisement.local_name, device.name)
            if name:
                self._devices[address] = device
                names[address] = name
        return names

    async def connect(self, address: str, on_lost: Callable[[], None]) -> None:
        await self.disconnect()

        def disconnected(client: BleakClient) -> None:
            if self._client is client:
                self._client = None
                on_lost()

        client = BleakClient(
            self._devices.get(address, address), disconnected_callback=disconnected,
            pair=True, timeout=60,
        )
        self._client = client
        try:
            await client.connect()
            self._connected_client()
        except BaseException:
            # The caller can cancel a connection attempt when closing the window.
            if self._client is client:
                await self.disconnect()
            raise

    def _connected_client(self) -> BleakClient:
        if self._client is None or not self._client.is_connected:
            raise ConnectionError("Связь с наушниками потеряна.")
        return self._client

    async def read(self) -> dict[str, int | str | None]:
        client = self._connected_client()
        snapshot = {}
        errors = []
        for key, (uuid, _) in READS.items():
            try:
                snapshot.update(decode_field(key, await client.read_gatt_char(uuid)))
            except (BleakError, OSError) as exc:
                self._connected_client()
                snapshot[key] = None
                errors.append(exc)
        self._connected_client()
        if len(errors) == len(READS):
            raise RuntimeError(f"Не удалось прочитать настройки наушников. {errors[0]}") from errors[0]
        return snapshot

    async def subscribe(self, on_update: Callable[[dict], None]) -> None:
        client = self._connected_client()
        for key, (uuid, _) in READS.items():
            def update(_sender, data, field=key):
                if client is self._client:
                    on_update(decode_field(field, data))
            try:
                await client.start_notify(uuid, update)
            except (BleakError, OSError):
                self._connected_client()  # Periodic reads cover unsupported notifications.

    async def _select_preset(self, client: BleakClient, value: str) -> None:
        uuid, assign = protocol.setting_command("eq", value)
        slots = protocol.eq_slots(await client.read_gatt_char(uuid))
        for slot in ("1", "2"):
            if slots.get("eq_slot" + slot) == value:
                await client.write_gatt_char(uuid, protocol.EQ_SLOT_VALUES[slot], response=True)
                return
        await client.write_gatt_char(uuid, assign, response=True)
        if slots.get("eq_active_slot") == "1":
            confirmed = protocol.eq_slots(await client.read_gatt_char(uuid))
            if confirmed.get("eq_slot2") != value:
                raise ValueError("Наушники не подтвердили пресет второго слота.")
            await client.write_gatt_char(uuid, protocol.EQ_SLOT_VALUES["2"], response=True)

    async def set_value(self, key: str, value: str) -> None:
        client = self._connected_client()
        if key == "eq":
            await self._select_preset(client, value)
            return
        if key == "timer":
            uuid = protocol.UUID_POWER_TIMER
            raw = await client.read_gatt_char(uuid)
            if timer_minutes(raw) is None or value not in ("15", "20"):
                raise ValueError("Неподдерживаемое значение таймера.")
            # Preserve the paired/paused timer returned by the device.
            payload = b"\x02" + raw[3:9] + (int(value) * 60).to_bytes(2, "big")
        elif key == "eq_active_slot":
            uuid, payload = protocol.UUID_EQ_PRESET, protocol.EQ_SLOT_VALUES[value]
        else:
            uuid, payload = protocol.setting_command("eq" if key == "eq_slot2" else key, value)
        await client.write_gatt_char(uuid, payload, response=True)

    async def disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except BaseException:
                if client.is_connected:
                    self._client = client
                raise


class DemoBackend:
    address = "DE:00:00:00:00:01"

    def __init__(self) -> None:
        self._on_lost: Callable[[], None] | None = None
        self._values: dict[str, int | str] = {
            "battery": 78, "eq": "marshall", "m_button": "eq", "prompts": "on",
            "eq_slot1": "marshall", "eq_slot2": "individual", "eq_active_slot": "1",
            "timer": "20",
        }

    async def scan(self) -> dict[str, str]:
        await asyncio.sleep(0.3)
        return {self.address: "Major V"}

    async def connect(self, address: str, on_lost: Callable[[], None]) -> None:
        if address != self.address:
            raise ConnectionError("Демоустройство не найдено.")
        await asyncio.sleep(0.2)
        self._on_lost = on_lost

    def _require_connection(self) -> None:
        if self._on_lost is None:
            raise ConnectionError("Демоустройство отключено.")

    async def read(self) -> dict[str, int | str]:
        self._require_connection()
        return self._values.copy()

    async def set_value(self, key: str, value: str) -> None:
        self._require_connection()
        if key in ("eq", "eq_slot2"):
            protocol.setting_command("eq", value)
            if key == "eq" and value == self._values["eq_slot1"]:
                self._values["eq_active_slot"] = "1"
            else:
                self._values["eq_slot2"] = value
                if key == "eq":
                    self._values["eq_active_slot"] = "2"
        elif key == "timer":
            if value not in ("15", "20"):
                raise ValueError("Неподдерживаемый таймер.")
        elif key == "eq_active_slot":
            if value not in ("1", "2"):
                raise ValueError("Неизвестный слот EQ.")
        else:
            protocol.setting_command(key, value)
        self._values[key] = value
        self._values["eq"] = self._values["eq_slot" + self._values["eq_active_slot"]]

    async def subscribe(self, on_update):
        self._require_connection()

    async def disconnect(self) -> None:
        self._on_lost = None

    def simulate_loss(self) -> None:
        callback, self._on_lost = self._on_lost, None
        if callback is not None:
            callback()

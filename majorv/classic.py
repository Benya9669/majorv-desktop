"""Look up paired Major V Classic endpoints in the OS Bluetooth inventory."""

import re
import sys

from scripts.individual_eq import SERVICE_UUID


_MODEL = re.compile(r"\bmajor[\s_-]+v\b", re.IGNORECASE)
_ADDRESS = re.compile(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}")
_CLASSIC_SERVICES = {
    SERVICE_UUID,
    "0000110b-0000-1000-8000-00805f9b34fb",  # Audio Sink
    "0000111e-0000-1000-8000-00805f9b34fb",  # Handsfree
}


def _normalize(address: str) -> str:
    address = address.upper().replace("-", ":")
    return address if _ADDRESS.fullmatch(address) and address != "00:00:00:00:00:00" else ""


def _bluez_candidates(objects: dict) -> dict[str, str]:
    candidates = {}
    for interfaces in objects.values():
        device = interfaces.get("org.bluez.Device1", {})
        if not device.get("Paired") or device.get("Blocked"):
            continue
        name, alias = device.get("Name", ""), device.get("Alias", "")
        if not (_MODEL.search(name) or _MODEL.search(alias)):
            continue
        # Public addresses alone are also valid for LE-only devices. Require
        # a Classic service in BlueZ's cached SDP results before using RFCOMM.
        uuids = {uuid.lower() for uuid in device.get("UUIDs", [])}
        address = _normalize(device.get("Address", ""))
        if address and _CLASSIC_SERVICES.intersection(uuids):
            candidates[address] = alias or name
    return candidates


async def _linux_devices() -> dict[str, str]:
    from dbus_fast import BusType, Message, MessageType, unpack_variants
    from dbus_fast.aio.message_bus import MessageBus

    bus = MessageBus(bus_type=BusType.SYSTEM)
    try:
        await bus.connect()
        reply = await bus.call(Message(
            destination="org.bluez", path="/",
            interface="org.freedesktop.DBus.ObjectManager", member="GetManagedObjects",
        ))
        if reply is None or reply.message_type != MessageType.METHOD_RETURN:
            detail = reply.error_name if reply else "нет ответа"
            raise RuntimeError(f"Не удалось получить сопряжённые устройства BlueZ ({detail}).")
        return _bluez_candidates(unpack_variants(reply.body[0]))
    finally:
        bus.disconnect()


async def _windows_devices(ble_address: str) -> dict[str, str]:
    from winrt.system import unbox_guid, unbox_string
    from winrt.windows.devices.bluetooth import BluetoothDevice, BluetoothLEDevice
    from winrt.windows.devices.enumeration import DeviceInformation, DeviceInformationKind

    address_key = "System.Devices.Aep.DeviceAddress"
    container_key = "System.Devices.Aep.ContainerId"
    # This overload name is shared by PyWinRT 3 and 4.
    enumerate_endpoints = DeviceInformation.find_all_async_with_kind_aqs_filter_and_additional_properties
    kind = DeviceInformationKind.ASSOCIATION_ENDPOINT
    paired_classic = BluetoothDevice.get_device_selector_from_pairing_state(True)
    endpoints = await enumerate_endpoints(paired_classic, [address_key, container_key], kind)
    candidates = {}
    containers = {}
    for device in endpoints:
        if not _MODEL.search(device.name):
            continue
        raw = device.properties.get(address_key)
        address = _normalize(unbox_string(raw)) if raw is not None else ""
        if address:
            candidates[address] = device.name
            value = device.properties.get(container_key)
            if value is not None:
                containers[address] = unbox_guid(value)

    if ble_address and len(candidates) > 1 and ble_address not in candidates and containers:
        # Dual-mode devices can share an OS container, but Windows can also
        # assign separate container IDs to a Major V's BR/EDR and LE endpoints.
        selector = BluetoothLEDevice.get_device_selector_from_bluetooth_address(
            int(ble_address.replace(":", ""), 16)
        )
        try:
            le_devices = await enumerate_endpoints(selector, [container_key], kind)
        except OSError:
            return candidates
        matches = {}
        for device in le_devices:
            value = device.properties.get(container_key)
            if value is not None:
                container = unbox_guid(value)
                if container.int:
                    matches.update({addr: candidates[addr] for addr in containers if containers[addr] == container})
        if matches:
            return matches
    return candidates


async def find_classic_devices(ble_address: str | None = None) -> dict[str, str]:
    """Return paired Classic candidates, preferring an OS-correlated BLE endpoint."""
    selected = _normalize(ble_address or "")
    if sys.platform == "win32":
        candidates = await _windows_devices(selected)
    elif sys.platform.startswith("linux"):
        candidates = await _linux_devices()
    else:
        raise RuntimeError("Поиск Bluetooth Classic доступен в Windows и Linux.")
    if selected in candidates:
        return {selected: candidates[selected]}
    return dict(sorted(candidates.items()))

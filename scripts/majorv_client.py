#!/usr/bin/env python
"""Small Marshall Major V BLE client based on captured ATT traffic."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from typing import Callable

from bleak import BleakClient, BleakScanner


UUID_M_BUTTON = "0000000d-1337-1dea-feed-c0ffee70c0de"
UUID_SOUND_PROMPTS = "0000000b-1337-1dea-feed-c0ffee70c0de"
UUID_POWER_TIMER = "00000032-1337-1dea-feed-c0ffee70c0de"
UUID_EQ_PRESET = "00000017-1337-1dea-feed-c0ffee70c0de"

UUID_STATUS = "0000000a-1337-1dea-feed-c0ffee70c0de"
UUID_ATT_STATUS = "00000007-1337-1dea-feed-c0ffee70c0de"
UUID_BATTERY = "00002a19-0000-1000-8000-00805f9b34fb"
UUID_BATTERY_STATUS = "00002bed-0000-1000-8000-00805f9b34fb"


M_BUTTON_VALUES = {
    "none": bytes.fromhex("00 00"),
    "voice": bytes.fromhex("00 01"),
    "eq": bytes.fromhex("00 08"),
    "spotify": bytes.fromhex("00 09"),
}

M_BUTTON_NAMES = {value: key for key, value in M_BUTTON_VALUES.items()}

EQ_PRESET_VALUES = {
    "marshall": bytes.fromhex("01 01 00"),
    "individual": bytes.fromhex("01 01 01"),
    "bass": bytes.fromhex("01 01 02"),
    "mid": bytes.fromhex("01 01 03"),
    "treble": bytes.fromhex("01 01 04"),
    "mid-reduction": bytes.fromhex("01 01 05"),
}

EQ_PRESET_NAMES = {value[-1]: key for key, value in EQ_PRESET_VALUES.items()}

EQ_SLOT_VALUES = {
    "1": bytes.fromhex("00 00"),
    "2": bytes.fromhex("00 01"),
}


def hex_bytes(value: bytes | bytearray) -> str:
    return bytes(value).hex(" ")


def decode_m_button(value: bytes | bytearray) -> str | None:
    data = bytes(value)
    if len(data) >= 2:
        return M_BUTTON_NAMES.get(data[-2:])
    return None


def decode_sound_prompts(value: bytes | bytearray) -> str | None:
    data = bytes(value)
    if data == bytes.fromhex("00 00"):
        return "off"
    if data == bytes.fromhex("ff ff"):
        return "on"
    return None


def decode_power_timer(value: bytes | bytearray) -> str | None:
    data = bytes(value)
    if len(data) < 2:
        return None
    seconds = int.from_bytes(data[-2:], "big")
    if seconds % 60:
        return f"tail={seconds}s"
    return f"not-connected={seconds // 60}min (tail field)"


def decode_eq_preset(value: bytes | bytearray) -> str | None:
    data = bytes(value)
    if not data:
        return None
    preset = EQ_PRESET_NAMES.get(data[-1])
    if preset is None:
        return None
    return f"{preset} ({data[-1]})"


def decode_status_blob(value: bytes | bytearray) -> str | None:
    data = bytes(value)
    pos = 0
    items: list[str] = []
    while pos + 7 <= len(data):
        item_id = int.from_bytes(data[pos : pos + 4], "big")
        status = int.from_bytes(data[pos + 4 : pos + 6], "big")
        length = data[pos + 6]
        pos += 7
        if pos + length > len(data):
            return None
        raw_text = data[pos : pos + length]
        pos += length
        try:
            text = raw_text.decode("utf-8")
        except UnicodeDecodeError:
            text = hex_bytes(raw_text)
        items.append(f"id={item_id} status=0x{status:04x} text={text!r}")
    if pos != len(data):
        return None
    return "; ".join(items)


DECODERS: dict[str, Callable[[bytes | bytearray], str | None]] = {
    "m-button": decode_m_button,
    "sound-prompts": decode_sound_prompts,
    "power-timer": decode_power_timer,
    "eq-preset": decode_eq_preset,
    "status": decode_status_blob,
}


def notification_handler(label: str) -> Callable[[object, bytearray], None]:
    def on_notification(sender: object, data: bytearray) -> None:
        decoded = DECODERS.get(label, lambda _value: None)(data)
        suffix = f" decoded={decoded}" if decoded else ""
        print(f"notify {label} sender={sender} value={hex_bytes(data)}{suffix}")

    return on_notification


async def read_optional(client: BleakClient, uuid: str, label: str) -> None:
    try:
        value = await client.read_gatt_char(uuid)
        decoded = DECODERS.get(label, lambda _value: None)(value)
        suffix = f" decoded={decoded}" if decoded else ""
        print(f"read {label}: {hex_bytes(value)}{suffix}")
    except Exception as exc:
        print(f"read {label}: ERROR {exc!r}")


async def start_notify_optional(client: BleakClient, uuid: str, label: str) -> None:
    try:
        await client.start_notify(uuid, notification_handler(label))
        print(f"notify enabled {label}")
    except Exception as exc:
        print(f"notify enable {label}: ERROR {exc!r}")


async def write_value(client: BleakClient, uuid: str, label: str, value: bytes) -> None:
    print(f"write {label}: {hex_bytes(value)}")
    await client.write_gatt_char(uuid, value, response=True)
    print("write ok")


def encode_power_timer(connected_paused_minutes: int, not_connected_minutes: int) -> bytes:
    """Encode the observed power timer command.

    Captured values:
    - 35 min / 15 min: 02 00 01 09 60 01 02 03 84
    - 40 min / 20 min: 02 00 01 09 60 01 02 04 b0

    The first six bytes look like a command prefix. The final two bytes equal
    the two timers in seconds, big-endian-ish split as observed:
    0x0384 = 900 seconds = 15 min, 0x04b0 = 1200 seconds = 20 min.

    The captured pair only changed one visible tail field, so this encoder is
    deliberately conservative and uses the tail for `not_connected_minutes`.
    """
    _ = connected_paused_minutes
    seconds = not_connected_minutes * 60
    if seconds < 0 or seconds > 0xFFFF:
        raise ValueError("timer must fit in uint16 seconds")
    return bytes.fromhex("02 00 01 09 60 01 02") + seconds.to_bytes(2, "big")


@dataclass(frozen=True)
class CommandContext:
    client: BleakClient
    args: argparse.Namespace


async def command_status(ctx: CommandContext) -> None:
    await read_optional(ctx.client, UUID_BATTERY, "battery")
    await read_optional(ctx.client, UUID_BATTERY_STATUS, "battery-status")
    await read_optional(ctx.client, UUID_M_BUTTON, "m-button")
    await read_optional(ctx.client, UUID_SOUND_PROMPTS, "sound-prompts")
    await read_optional(ctx.client, UUID_POWER_TIMER, "power-timer")
    await read_optional(ctx.client, UUID_EQ_PRESET, "eq-preset")
    await read_optional(ctx.client, UUID_STATUS, "status")


async def command_watch(ctx: CommandContext) -> None:
    await asyncio.sleep(ctx.args.seconds)


async def command_m_button(ctx: CommandContext) -> None:
    await write_value(ctx.client, UUID_M_BUTTON, "m-button", M_BUTTON_VALUES[ctx.args.value])


async def command_eq(ctx: CommandContext) -> None:
    await write_value(ctx.client, UUID_EQ_PRESET, "eq-preset", EQ_PRESET_VALUES[ctx.args.preset])


async def command_eq_slot(ctx: CommandContext) -> None:
    await write_value(ctx.client, UUID_EQ_PRESET, "eq-slot", EQ_SLOT_VALUES[ctx.args.slot])


async def command_prompts(ctx: CommandContext) -> None:
    value = bytes.fromhex("ff ff") if ctx.args.enabled else bytes.fromhex("00 00")
    await write_value(ctx.client, UUID_SOUND_PROMPTS, "sound-prompts", value)


async def command_timer(ctx: CommandContext) -> None:
    value = encode_power_timer(ctx.args.connected_paused, ctx.args.not_connected)
    await write_value(ctx.client, UUID_POWER_TIMER, "power-timer", value)


async def run(args: argparse.Namespace) -> None:
    address = args.address
    if args.name:
        print(f"scanning for {args.name!r}...")
        device = await BleakScanner.find_device_by_filter(
            lambda device, advertisement: (
                args.name.lower() in (device.name or "").lower()
                or args.name.lower() in (advertisement.local_name or "").lower()
            ),
            timeout=args.scan_seconds,
        )
        if device is None:
            raise SystemExit(f"Could not find BLE device matching {args.name!r}")
        address = device.address
        print(f"found {device.name!r} at {address}")

    async with BleakClient(address, pair=args.pair, timeout=args.connect_timeout) as client:
        print(f"connected={client.is_connected}")
        await start_notify_optional(client, UUID_STATUS, "status/0000000a")
        await start_notify_optional(client, UUID_ATT_STATUS, "att-status/00000007")
        await start_notify_optional(client, UUID_EQ_PRESET, "eq-preset/00000017")
        await start_notify_optional(client, UUID_BATTERY, "battery")
        await start_notify_optional(client, UUID_BATTERY_STATUS, "battery-status")

        ctx = CommandContext(client=client, args=args)
        await args.func(ctx)

        if args.after_seconds:
            await asyncio.sleep(args.after_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    device = parser.add_mutually_exclusive_group(required=True)
    device.add_argument("--address", help="BLE address or platform device identifier")
    device.add_argument("--name", help="Scan and connect to a device matching this name")
    parser.add_argument("--scan-seconds", type=float, default=15.0)
    parser.add_argument("--connect-timeout", type=float, default=30.0)
    parser.add_argument("--pair", action="store_true", help="Ask Bleak/OS to pair before connecting")
    parser.add_argument("--after-seconds", type=float, default=2.0)

    subparsers = parser.add_subparsers(required=True)

    status = subparsers.add_parser("status")
    status.set_defaults(func=command_status)

    watch = subparsers.add_parser("watch")
    watch.add_argument("--seconds", type=float, default=30.0)
    watch.set_defaults(func=command_watch)

    m_button = subparsers.add_parser("m-button")
    m_button.add_argument("value", choices=sorted(M_BUTTON_VALUES))
    m_button.set_defaults(func=command_m_button)

    eq = subparsers.add_parser("eq")
    eq.add_argument("preset", choices=sorted(EQ_PRESET_VALUES))
    eq.set_defaults(func=command_eq)

    eq_slot = subparsers.add_parser("eq-slot")
    eq_slot.add_argument("slot", choices=sorted(EQ_SLOT_VALUES))
    eq_slot.set_defaults(func=command_eq_slot)

    prompts = subparsers.add_parser("prompts")
    prompts_group = prompts.add_mutually_exclusive_group(required=True)
    prompts_group.add_argument("--on", dest="enabled", action="store_true")
    prompts_group.add_argument("--off", dest="enabled", action="store_false")
    prompts.set_defaults(func=command_prompts)

    timer = subparsers.add_parser("timer")
    timer.add_argument("--connected-paused", type=int, required=True)
    timer.add_argument("--not-connected", type=int, required=True)
    timer.set_defaults(func=command_timer)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()

"""Read, inspect, and apply verified Major V Individual EQ profiles."""

import argparse
import asyncio
import hashlib
import json
import struct
import sys
from collections.abc import Iterator
from pathlib import Path


SERVICE_UUID = "00000000-0000-0000-0099-aabbccddeeff"
BANDS = (160, 400, 1000, 2500, 6250)
# Captured read of the saved Individual parameter record (frame 7196).
READ_INDIVIDUAL = bytes.fromhex("05 5a 06 00 00 0a 00 ef e8 03")
REFERENCE_DB = {
    "f429bbdae666c4ba4ab8125f76d34987205438a54efba94d71514f840d10b3d1": 6,
    "882292ee31f61014b2d678f4b6b728536aef95dfbb44e7ffa8bda5ac6ae4d6b4": -6,
    "067f570d21087a60387b0e5238eb63244a97c742ded6d50a5a71cd6d78b56244": 0,
}


class RaceStream:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, chunk: bytes) -> Iterator[bytes]:
        self.buffer.extend(chunk)
        while len(self.buffer) >= 4:
            if self.buffer[0] not in (0x05, 0x15):
                raise ValueError("Expected a RACE header at the frame boundary")
            size = struct.unpack_from("<H", self.buffer, 2)[0] + 4
            if size < 6:
                raise ValueError("RACE length is too small for the command ID")
            if len(self.buffer) < size:
                break
            frame = bytes(self.buffer[:size])
            del self.buffer[:size]
            yield frame

    def finish(self):
        if self.buffer:
            raise ValueError(f"Incomplete RACE frame ({len(self.buffer)} bytes)")


def band_gains(frame: bytes, frequency_offset: int) -> tuple[int, ...]:
    gains = []
    for i, expected in enumerate(BANDS):
        frequency, gain = struct.unpack_from("<Ii", frame, frequency_offset + 18 * i)
        if frequency != expected * 100 or not -600 <= gain <= 600:
            raise ValueError(f"Unexpected Major V band at index {i}")
        gains.append(gain)
    return tuple(gains)


def saved_profile(frame: bytes) -> tuple[int, ...]:
    # RACE response, 0x0A00, uint16LE record size = 185 (frame 7200).
    if len(frame) != 193 or frame[:8] != bytes.fromhex("05 5b bd 00 00 0a b9 00"):
        raise ValueError("Expected the 185-byte Individual parameter record")
    for i, q in enumerate((70, 70, 100, 100, 100)):
        index = 13 + 18 * i
        filter_type = frame[index : index + 2]
        q_value = struct.unpack_from("<I", frame, index + 14)[0]
        if filter_type != b"\x01\x02" or q_value != q:
            raise ValueError(f"Unexpected Major V filter parameters at index {i}")
    return band_gains(frame, 15)


def format_bands(gains: tuple[int, ...]) -> str:
    return ", ".join(f"{hz} Hz {gain / 100:+.2f} dB" for hz, gain in zip(BANDS, gains, strict=True))


def describe(frame: bytes) -> str:
    cmd = struct.unpack_from("<H", frame, 4)[0]
    label = f"RACE 0x{cmd:04X} type=0x{frame[1]:02X} ({len(frame)} bytes)"
    if frame == READ_INDIVIDUAL:
        return label + "  Read saved Individual EQ"
    if cmd == 0x0A00 and len(frame) == 193:
        # Other settings records use this command too. Only label matching band data.
        try:
            gains = saved_profile(frame)
        except ValueError:
            return label
        return label + "  " + format_bands(gains)
    expected_size = {0x0E2B: 199, 0x0E03: 451}.get(cmd)
    if frame[1] in (0x5A, 0x5C) and expected_size and len(frame) != expected_size:
        raise ValueError(f"Unexpected length for {label}; expected {expected_size} bytes")
    if cmd == 0x0E2B and len(frame) == 199:
        return label + "  " + format_bands(band_gains(frame, 13))
    if cmd == 0x0E03 and len(frame) == 451:
        block = frame[7:]
        sections = [struct.unpack_from("<HH", block, 4 + 110 * i) for i in range(4)]
        if sorted(sections) != [(1, 53), (2, 53), (5, 53), (6, 53)]:
            raise ValueError("Unexpected sample rates or section lengths in DSP block")
        digest = hashlib.sha256(block).hexdigest()
        gain = REFERENCE_DB.get(digest)
        match = "no reference match" if gain is None else f"reference: 160 Hz {gain:+d} dB"
        return f"{label}  SHA-256={digest} ({match})"
    # Short responses carry the same command IDs as full writes.
    return label


def decode(path: Path):
    stream = RaceStream()
    with path.open("rb") as capture:
        while chunk := capture.read(8192):
            for frame in stream.feed(chunk):
                print(describe(frame))
    stream.finish()


def probe(classic_address: str, timeout: int, *, read_profile: bool = False, json_output=False,
          apply_levels=None, expected=None) -> int:
    from PySide6.QtBluetooth import (
        QBluetoothAddress, QBluetoothServiceInfo, QBluetoothSocket, QBluetoothUuid,
    )
    from PySide6.QtCore import QCoreApplication, QIODevice, QTimer, QUuid

    app = QCoreApplication([])
    address = QBluetoothAddress(classic_address)
    if address.isNull():
        raise ValueError("Expected the paired device's Classic Bluetooth MAC address")
    uuid = QBluetoothUuid(QUuid(SERVICE_UUID))
    socket = QBluetoothSocket(QBluetoothServiceInfo.Protocol.RfcommProtocol)
    stream = RaceStream()
    timer = QTimer()
    timer.setSingleShot(True)
    connected = False
    finished = False
    sequence = None
    awaiting = None

    def advance(frame=None):
        nonlocal awaiting
        try:
            request, awaiting = sequence.send(frame)
            if socket.write(request) != len(request):
                raise ValueError("Could not queue the EQ request")
            timer.start(timeout * 1000)
        except StopIteration as done:
            finish(0, json.dumps(done.value) if json_output else f"Saved and verified: {done.value} dB")
        except ValueError as exc:
            finish(1, str(exc))

    def finish(code, message):
        nonlocal finished
        if finished:
            return
        finished = True
        timer.stop()
        print(message, file=sys.stderr if code else sys.stdout)
        app.exit(code)

    def on_connected():
        nonlocal connected, sequence
        connected = True
        print("RFCOMM connected by UUID.", flush=True, file=sys.stderr if json_output else sys.stdout)
        if apply_levels is not None:
            from scripts.individual_eq_apply import apply_sequence
            sequence = apply_sequence(apply_levels, expected)
            advance()
            return
        if read_profile and socket.write(READ_INDIVIDUAL) != len(READ_INDIVIDUAL):
            finish(1, f"Could not queue the Individual profile request: {socket.errorString()}")
            return
        timer.start(timeout * 1000)

    def on_data():
        try:
            for frame in stream.feed(bytes(socket.readAll())):
                if sequence is not None:
                    if frame[1] == 0x5B and int.from_bytes(frame[4:6], "little") == awaiting:
                        advance(frame)
                        if finished:
                            return
                    continue
                if read_profile:
                    if frame[1] == 0x5B and frame[4:6] == b"\x00\x0a":
                        gains = saved_profile(frame)
                        result = (json.dumps([gain / 100 for gain in gains]) if json_output
                                  else "Saved Individual EQ: " + format_bands(gains))
                        finish(0, result)
                        return
                    continue
                print(describe(frame), flush=True)
                if int.from_bytes(frame[4:6], "little") == 0x0E2B and len(frame) == 199:
                    finish(0, "Observed five bands in an incoming message.")
                    return
        except ValueError as exc:
            finish(1, str(exc))

    def on_timeout():
        if sequence is not None:
            finish(2, "Timed out while applying EQ. Re-read the saved profile before retrying.")
        elif connected:
            finish(2, "RFCOMM connected, but no complete five-band profile arrived.")
        else:
            finish(1, "Service lookup or connection timed out. Check pairing and the Classic address.")

    def start():
        print(f"Looking up {SERVICE_UUID} on {address.toString()} ...", flush=True,
              file=sys.stderr if json_output else sys.stdout)
        timer.start(timeout * 1000)
        mode = QIODevice.OpenModeFlag.ReadWrite if read_profile or apply_levels is not None else QIODevice.OpenModeFlag.ReadOnly
        socket.connectToService(address, uuid, mode)

    timer.timeout.connect(on_timeout)
    socket.connected.connect(on_connected)
    socket.readyRead.connect(on_data)
    socket.disconnected.connect(lambda: finish(1, "Classic connection closed by the peer."))
    socket.errorOccurred.connect(lambda _: finish(1, f"Bluetooth error: {socket.errorString()}"))
    QTimer.singleShot(0, start)
    if apply_levels is not None:
        # Keep shutdown bounded even if a peer keeps accepting individual steps slowly.
        QTimer.singleShot(40000, lambda: finish(2, "Save timed out. Read the profile again."))
    result = app.exec()
    socket.abort()
    return result


def discover_devices(ble_address: str | None, timeout: int) -> dict[str, str]:
    from majorv.classic import find_classic_devices

    try:
        candidates = asyncio.run(asyncio.wait_for(find_classic_devices(ble_address), timeout))
    except TimeoutError as exc:
        raise RuntimeError("Classic discovery timed out. Check that Bluetooth is enabled.") from exc
    except Exception as exc:
        raise RuntimeError(f"Classic discovery failed: {exc}") from exc
    return dict(sorted(candidates.items(), key=lambda pair: (pair[1].casefold(), pair[0])))


def select_device(devices: dict[str, str], interactive: bool) -> str:
    if not devices:
        raise ValueError("No paired Major V found. Pair the headphones in the system Bluetooth settings.")
    if len(devices) == 1:
        return next(iter(devices))

    print("Several paired Major V devices found:", file=sys.stderr)
    for index, (address, name) in enumerate(devices.items(), 1):
        print(f"  {index}. {name} ({address})", file=sys.stderr)
    if not interactive:
        raise ValueError("Pass the desired Classic address or select the headphones in the app.")
    print("Select a device number: ", end="", file=sys.stderr, flush=True)
    choice = sys.stdin.readline().strip()
    if not choice.isascii() or not choice.isdecimal() or not 1 <= int(choice) <= len(devices):
        raise ValueError("Invalid device selection.")
    return list(devices)[int(choice) - 1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    offline = modes.add_parser("decode", help="Inspect a raw, single-direction RFCOMM byte stream")
    offline.add_argument("stream", type=Path)
    devices = modes.add_parser("devices", help="List paired Major V Classic devices")
    devices.add_argument("--json", action="store_true", help="Print an address-to-name JSON object")
    live = modes.add_parser("probe", help="Connect by UUID and listen without sending RACE commands")
    read = modes.add_parser("read", help="Request the saved five-band Individual EQ profile")
    write = modes.add_parser("apply", help="Save five Individual EQ bands and verify the readback")
    write.add_argument("--expect", type=int, nargs=5, metavar="CDB", help="Expected current gains in hundredths of a dB")
    write.add_argument("--json", action="store_true")
    read.add_argument("--json", action="store_true", help="Print a JSON array of five gains in dB")
    for subparser in (live, read, write):
        subparser.add_argument("address", nargs="?", help="Explicit Classic MAC (default: discover paired Major V)")
    gains = write.add_mutually_exclusive_group(required=True)
    gains.add_argument("gain", nargs="?", type=int, choices=(-6, 0, 6),
                       help="Legacy 160 Hz gain in dB with four flat bands")
    gains.add_argument("--bands", type=float, nargs=5,
                       metavar=("160Hz", "400Hz", "1kHz", "2.5kHz", "6.25kHz"),
                       help="Five gains in dB, from -6 to +6 in steps of 0.12")
    for subparser in (devices, live, read, write):
        subparser.add_argument("--ble-address", help="Prefer the Classic endpoint associated with this BLE device")
        subparser.add_argument("--timeout", type=int, default=20, metavar="SECONDS")
    args = parser.parse_args()
    try:
        if args.mode == "decode":
            decode(args.stream)
            return 0
        if not 1 <= args.timeout <= 3600:
            parser.error("--timeout must be between 1 and 3600 seconds")
        if args.mode == "devices":
            candidates = discover_devices(args.ble_address, args.timeout)
            if args.json:
                print(json.dumps(candidates))
            else:
                for address, name in candidates.items():
                    print(f"{name} ({address})")
                if not candidates:
                    print("No paired Major V found.")
            return 0
        address = args.address
        json_output = getattr(args, "json", False)
        if args.mode == "apply" and args.bands is not None:
            from scripts.individual_eq_apply import supports_curve
            if not supports_curve(args.bands):
                raise ValueError("Unsupported gains. Use five slider values from -6 to +6 dB in steps of 0.12.")
        if address is None:
            candidates = discover_devices(args.ble_address, args.timeout)
            address = select_device(candidates, not json_output and sys.stdin.isatty())
        if args.mode == "apply":
            return probe(address, args.timeout, apply_levels=args.bands if args.bands is not None else args.gain,
                         expected=args.expect, json_output=json_output)
        return probe(address, args.timeout, read_profile=args.mode == "read", json_output=json_output)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    if not __package__:
        # Support the documented direct script invocation from any working directory.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.exit(main())

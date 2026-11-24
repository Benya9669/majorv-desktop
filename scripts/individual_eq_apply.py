"""Apply and read back a five-band Individual profile in the Major V EQ bank.

The generator yields (request, expected response command) pairs. The Qt socket
passes matching replies back into it so every step is acknowledged before the
next. All record IDs and data layouts are specific to the captured EQ bank.
"""
import hashlib
import math
import struct

from scripts.individual_eq import BANDS, READ_INDIVIDUAL, REFERENCE_DB, saved_profile
from scripts.individual_eq_dsp import (
    generate_curve_dsp, generate_dsp, peak_headroom_hundredths, slider_from_hundredths,
    slider_gain_hundredths,
)


def _frame(command, data, kind=0x5A):
    return struct.pack("<BBHH", 5, kind, len(data) + 2, command) + data


def _read_record(key):
    reply = yield _frame(0x0A00, struct.pack("<HH", key, 1000)), 0x0A00
    if (len(reply) < 8 or reply[:2] != b"\x05\x5b" or
            struct.unpack_from("<HHH", reply, 2) != (len(reply) - 4, 0x0A00, len(reply) - 8)):
        raise ValueError(f"Unexpected response to EQ record read (0x{key:04X})")
    return reply[8:]


def _expect(request, command, expected_data):
    reply = yield request, command
    if reply != _frame(command, expected_data, 0x5B):
        raise ValueError(f"Headphones rejected Individual EQ step 0x{command:04X}")


def _prepare(size):
    yield from _expect(_frame(0x0A03, struct.pack("<H", size)), 0x0A03, b"\x01")


def _store(key, payload, prepare=True):
    if prepare:
        yield from _prepare(len(payload))
    yield from _expect(_frame(0x0A01, struct.pack("<H", key) + payload), 0x0A01, b"\x00")


def _parameters(gains):
    data = bytearray(5)
    for hz, gain, width, q in zip(BANDS, gains, (22857, 57142, 100000, 250000, 625000),
                                 (70, 70, 100, 100, 100), strict=True):
        data.extend(struct.pack("<BBIiII", 1, 2, hz * 100, gain, width, q))
    return bytes(data) + (b"\x00\x02" + bytes(16)) * 5


_CATEGORY = bytes.fromhex("65 00 00 00 ff ff ff ff 66 00 00 00 05 00 00 00 00 00")
_BANK = bytes.fromhex("02 00 00 00 02 e4 01 00 03 e4")
_MAPPING = bytes.fromhex(
    "06 00 02 00 00 00 10 e4 01 00 2a e4 02 00 00 00 11 e4 01 00 2b e4 "
    "01 00 00 00 12 e4 01 00 00 00 13 e4 01 00 00 00 14 e4 01 00 00 00 2c e4"
)


def curve_positions(levels_db):
    """Map nominal dB or exact device readback dB onto the five slider positions."""
    if not isinstance(levels_db, (list, tuple)) or len(levels_db) != len(BANDS):
        raise ValueError("Expected five Individual EQ gains in dB")
    positions = []
    for level in levels_db:
        if type(level) not in (int, float) or not -6 <= level <= 6:
            raise ValueError("Individual EQ gain must be between -6 and +6 dB")
        hundredths = round(level * 100)
        if not math.isclose(level, hundredths / 100, rel_tol=0, abs_tol=1e-8):
            raise ValueError("Individual EQ gain must match a 0.12 dB slider step")
        if hundredths % 12 == 0:
            positions.append(50 + hundredths // 12)
        else:
            positions.append(slider_from_hundredths(hundredths))
    return tuple(positions)


def supports_curve(levels_db):
    try:
        curve_positions(levels_db)
    except ValueError:
        return False
    return True


def apply_sequence(levels_db, expected=None):
    """Yield acknowledged requests. The optional stale-state check uses raw hundredths."""
    if type(levels_db) is int and levels_db in (-6, 0, 6):
        # Preserve the original one-argument CLI's section order and reference hashes.
        sliders = curve_positions((levels_db, 0, 0, 0, 0))
        dsp = generate_dsp(sliders[0])
        if REFERENCE_DB.get(hashlib.sha256(dsp).hexdigest()) != levels_db:
            raise ValueError("The DSP block does not match the reference capture")
    else:
        sliders = curve_positions(levels_db)
        dsp = generate_curve_dsp(sliders)
    target = tuple(slider_gain_hundredths(s) for s in sliders)
    params = _parameters(target)
    peak = peak_headroom_hundredths(sliders)
    tail = struct.pack("<ii", peak, peak)

    current = yield READ_INDIVIDUAL, 0x0A00
    previous = saved_profile(current)
    if expected is not None and tuple(expected) != previous:
        raise ValueError("The headset profile changed. Read it again before applying.")
    if current[8:] != _parameters(previous):
        raise ValueError("Unknown Individual parameter layout")
    for key, payload in ((0xEF10, _CATEGORY), (0xE401, _BANK), (0xE402, _MAPPING)):
        if (yield from _read_record(key)) != payload:
            raise ValueError("The EQ bank layout differs from the recorded Major V layout")

    # Frames 9005/9006 and their single 0x0E03 acknowledgement.
    live = _frame(0x0E2B, params + tail) + _frame(0x0E03, b"\x00" + dsp)
    yield from _expect(live, 0x0E03, b"\x00")
    yield from _store(0xEF00, params)
    yield from _store(0xEF10, _CATEGORY)
    yield from _store(0xEF20, tail, prepare=False)
    for key, payload in ((0xE401, _BANK), (0xE402, _MAPPING)):
        if (yield from _read_record(key)) != payload:
            raise ValueError("The EQ bank mapping changed during save")
    yield from _store(0xE42C, dsp)
    yield from _store(0xE402, _MAPPING)
    yield from _prepare(len(_BANK))
    yield from _expect(_frame(0x09FD, bytes.fromhex("00 2c e4")), 0x09FD, b"\x00")
    for key, payload in ((0xE401, _BANK), (0xE402, _MAPPING)):
        if (yield from _read_record(key)) != payload:
            raise ValueError("The EQ bank mapping could not be confirmed")
    yield from _expect(_frame(0x0900, b"\x00\x00\x06"), 0x0900, bytes(3))
    yield from _expect(_frame(0x0901, bytes(2)), 0x0901, bytes.fromhex("00 00 00 06"))

    # Read actual persisted bytes for all three records independently of the write ACKs.
    if (yield from _read_record(0xE42C)) != dsp:
        raise ValueError("Saved DSP coefficients differ from the requested block")
    if (yield from _read_record(0xEF20)) != tail:
        raise ValueError("Saved Individual EQ headroom differs from the requested curve")
    readback = yield READ_INDIVIDUAL, 0x0A00
    result = saved_profile(readback)
    if readback[8:] != params:
        raise ValueError("Saved Individual EQ parameters differ from the requested curve")
    return [gain / 100 for gain in result]

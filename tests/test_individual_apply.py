import hashlib
import struct
import unittest

from scripts.individual_eq_apply import (
    _BANK, _CATEGORY, _MAPPING, _parameters, apply_sequence, curve_positions, supports_curve,
)


def response(cmd, data):
    return struct.pack("<BBHH", 5, 0x5b, 2 + len(data), cmd) + data


def record(data):
    return response(0x0a00, struct.pack("<H", len(data)) + data)


def simulate_save(levels, corrupt_readback=None):
    sequence = apply_sequence(levels, expected=[0] * 5)
    req, cmd = next(sequence)
    store = {0xef00: _parameters([0] * 5), 0xef10: _CATEGORY, 0xe401: _BANK, 0xe402: _MAPPING}
    requests = []
    while True:
        requests.append(req)
        if cmd == 0x0a00:
            key = int.from_bytes(req[6:8], "little")
            value = store[key]
            if len(requests) > 22 and key == corrupt_readback:
                # Flipping the final inactive byte of EF00 leaves all five gains intact.
                value = value[:-1] + bytes([value[-1] ^ 1])
            reply = record(value)
        elif cmd == 0x0a01:
            key = int.from_bytes(req[6:8], "little")
            store[key] = req[8:]
            reply = response(cmd, bytes(1))
        else:
            reply = response(cmd, {
                0x0e03: bytes(1), 0x0a03: b"\x01", 0x09fd: bytes(1),
                0x0900: bytes(3), 0x0901: b"\x00\x00\x00\x06",
            }[cmd])
        try:
            req, cmd = sequence.send(reply)
        except StopIteration as done:
            return requests, done.value


class SaveTests(unittest.TestCase):
    def test_captured_transactions_and_independent_readback(self):
        # SHA-256 covers all phone requests from the live curve through 0x0901.
        # The first three are original frames 8447..8540, 8662..8760, 9005..9101.
        # Five-value requests use the all-band capture's sample-rate order.
        for levels, expected, readback in (
            (6, "a87ab6879f28a68fb32603d441d294f0b48d78fe6e3966cea5dc54f2648f8d5b", [6, 0, 0, 0, 0]),
            (-6, "5fcf398f0b9b04f970b744706c41882f074eedef72d01735f41229407a1c2cee", [-6, 0, 0, 0, 0]),
            (0, "668ae401e5b5c0c9131c485191135d89416626b8e84597b4d2d249a08568530f", [0] * 5),
            # Frames 29969..30094, 31220..31331 and 31741..31853.
            ([0, 0, 0, 0, 6], "473c18d27201d1194093debc510005fbfc08734134bfbf36289e6651ccc186e0", [0, 0, 0, 0, 6]),
            ([6, -6, 0, 0, 0], "e18cee30f59f852af7f45d848df369a66b62d596f67e84aceec6047853806713", [6, -6, 0, 0, 0]),
            ([0, 0, -6, 6, 0], "b579c1ee21935b7a205d8e9bf5f0704c567cb805c761a6b74a2d114f05bf2b2a", [0, 0, -6, 6, 0]),
            # Frames 32836..32939 and 33257..33372. Nominal +0.12 reads back as +0.11.
            ([-6, 6, -6, 6, 6], "f968b416b063a8ddb800167673a26693706a999ce63a1928b75d2bd58ea6ea44", [-6, 6, -6, 6, 6]),
            ([-6, 6, .12, -6, 6], "52f35e9cb9e72dc90a284af51984133191a58f1602294fc9a8fb2d4a4d855ec8", [-6, 6, .11, -6, 6]),
        ):
            with self.subTest(levels=levels):
                requests, result = simulate_save(levels)
                self.assertEqual(result, readback)
                self.assertEqual(len(requests), 25)
                self.assertEqual(hashlib.sha256(b"".join(requests[4:22])).hexdigest(), expected)
                self.assertEqual([struct.unpack_from("<H", req, 6)[0] for req in requests[-3:]],
                                 [0xe42c, 0xef20, 0xef00])

    def test_readback_verifies_every_persisted_byte(self):
        for key, error in ((0xe42c, "DSP"), (0xef20, "headroom"), (0xef00, "parameters")):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, error):
                simulate_save([0, 0, -6, 6, 0], corrupt_readback=key)

    def test_accepts_only_nominal_steps_or_actual_device_values(self):
        self.assertEqual(curve_positions([0.11, 0.12, 0.24, -0.11, 6]), (51, 51, 52, 49, 100))
        for levels in (None, [0] * 4, [0] * 6, [0, 0, 0, 0, True], [0, 0, 0, 0, .111],
                       [0, 0, 0, 0, .13], [0, 0, 6.12, 0, 0], [0, float("nan"), 0, 0, 0]):
            with self.subTest(levels=levels):
                self.assertFalse(supports_curve(levels))
                with self.assertRaises(ValueError):
                    next(apply_sequence(levels))

    def test_stops_on_stale_settings_or_unknown_bank(self):
        seq = apply_sequence(6, [0] * 5)
        next(seq)
        with self.assertRaisesRegex(ValueError, "changed"):
            seq.send(record(_parameters([600, 0, 0, 0, 0])))
        seq = apply_sequence(6)
        next(seq)
        seq.send(record(_parameters([0] * 5)))
        with self.assertRaisesRegex(ValueError, "layout"):
            seq.send(record(b"unknown bank"))
        with self.assertRaises(ValueError):
            next(apply_sequence(3))

    def test_rejected_live_update_stops_before_any_persistent_write(self):
        seq = apply_sequence([6, -6, 0, 0, 0])
        next(seq)
        for data in (_parameters([0] * 5), _CATEGORY, _BANK, _MAPPING):
            req, cmd = seq.send(record(data))
        self.assertEqual(cmd, 0x0e03)
        with self.assertRaisesRegex(ValueError, "rejected"):
            seq.send(response(cmd, b"\x01"))

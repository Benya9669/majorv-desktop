import hashlib
import struct
import unittest

from scripts.individual_eq import BANDS, READ_INDIVIDUAL, RaceStream, describe, saved_profile


def frame(command, size, packet_type=0x5A):
    result = bytearray(size)
    struct.pack_into("<BBHH", result, 0, 5, packet_type, size - 4, command)
    return result


class RaceTests(unittest.TestCase):
    def test_saved_profile_read_response(self):
        self.assertEqual(READ_INDIVIDUAL.hex(), "055a0600000a00efe803")
        reply = frame(0x0A00, 193, packet_type=0x5B)
        struct.pack_into("<H", reply, 6, 185)
        gains = (-600, -12, 0, 12, 600)
        for i, frequency in enumerate(BANDS):
            q = 70 if i < 2 else 100
            struct.pack_into("<BBIiII", reply, 13 + 18 * i, 1, 2, frequency * 100, gains[i], 0, q)
        self.assertEqual(saved_profile(reply), gains)
        for offset, value in [(0, 0x15), (1, 0x5A), (2, 191), (4, 1), (6, 184),
                              (13, 0), (15, 0), (21, 0), (27, 100)]:
            with self.subTest(offset=offset):
                invalid = reply.copy()
                invalid[offset] = value
                with self.assertRaises(ValueError):
                    saved_profile(invalid)
        with self.assertRaises(ValueError):
            saved_profile(reply[:-1])

    def test_stream_handles_split_frames_and_short_responses(self):
        profile = frame(0x0E2B, 199)
        for i, frequency in enumerate(BANDS):
            gain = -600 if i == 0 else 0
            struct.pack_into("<Ii", profile, 13 + 18 * i, frequency * 100, gain)
        ack = frame(0x0E03, 7, packet_type=0x5B)
        stream = RaceStream()
        self.assertEqual(list(stream.feed(profile[:3])), [])
        self.assertEqual(list(stream.feed(profile[3:103])), [])
        messages = list(stream.feed(profile[103:] + ack))
        self.assertEqual(messages, [profile, ack])
        self.assertIn("160 Hz -6.00 dB", describe(messages[0]))
        self.assertIn("6250 Hz +0.00 dB", describe(messages[0]))
        self.assertNotIn("SHA", describe(messages[1]))
        stream.finish()

    def test_checks_all_four_dsp_sections_before_hashing(self):
        dsp = frame(0x0E03, 451)
        for i, rate in enumerate((1, 6, 2, 5)):
            struct.pack_into("<HH", dsp, 11 + i * 110, rate, 53)
        self.assertIn(hashlib.sha256(dsp[7:]).hexdigest(), describe(dsp))
        self.assertIn("no reference match", describe(dsp))
        dsp[11 + 110] = 2
        with self.assertRaises(ValueError):
            describe(dsp)

    def test_rejects_bad_lengths_and_incomplete_stream(self):
        with self.assertRaises(ValueError):
            list(RaceStream().feed(b"\x05\x5A\x01\x00"))
        with self.assertRaises(ValueError):
            describe(frame(0x0E2B, 198))
        stream = RaceStream()
        list(stream.feed(frame(0x0E03, 451)[:-1]))
        with self.assertRaises(ValueError):
            stream.finish()

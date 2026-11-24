import contextlib
import io
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.individual_eq import BANDS
from scripts.individual_eq_dsp import generate_curve_dsp
from scripts.inspect_eq_capture import inspect


def row(number, side, payload, dlci=42, session=1, frame_type=0xEF):
    return "\t".join(map(str, (
        number, 0, 1, session, 3, dlci, frame_type, side,
        "00:00:00:00:00:01", "00:00:00:00:00:02", len(payload), payload.hex(),
    )))


class CaptureTests(unittest.TestCase):
    def test_verify_mixed_pair_and_reject_corruption_or_cross_link_pair(self):
        # Final mixed curve, outgoing frames 33257/33258. The 1000 Hz slider at
        # 51 encodes as +0.11 dB in the parameter record.
        params = bytearray(199)
        params[:6] = bytes.fromhex("05 5a c3 00 2b 0e")
        for i, (hz, gain) in enumerate(zip(BANDS, (-600, 600, 11, -600, 600))):
            struct.pack_into("<Ii", params, 13 + 18 * i, 100 * hz, gain)
        struct.pack_into("<ii", params, 191, 506, 506)
        dsp = bytes.fromhex("05 5a bf 01 03 0e 00") + generate_curve_dsp((0, 100, 51, 0, 100))
        for payloads in ([row(1, 0, params + dsp)], [
            row(1, 0, params), row(2, 0, dsp[:2]), row(3, 0, dsp[2:]),
        ]):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                inspect(payloads, 1, None, False, verify_dsp=True)
            self.assertIn("1 distinct curves, 1 mixed pairs", output.getvalue())
        for following, error in (
            (row(2, 0, dsp[:-1] + bytes([dsp[-1] ^ 1])), "DSP byte 443"),
            (row(2, 0, dsp, session=2), "no preceding"),
            (row(2, 1, dsp), "no following"),
            (row(2, 0, b"", frame_type=0x43), "no following"),
        ):
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                inspect([row(1, 0, params), following], 1, None, False, verify_dsp=True)
        params[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "captured headroom"):
            inspect([row(1, 0, params + dsp)], 1, None, False, verify_dsp=True)

    def test_separate_streams_and_directions_before_frame_filter(self):
        request = bytes.fromhex("055a0300341201")
        reply = bytes.fromhex("055b0300341202")
        rows = [
            row(8, 0, request[:2]), row(9, 1, reply), row(10, 0, request[2:] + request),
            row(11, 1, request[:4], dlci=12), row(12, 1, request[4:]),
            row(13, 1, b"", dlci=12, frame_type=0x43),
            row(14, 1, request[4:], dlci=12), row(15, 1, request, session=2),
        ]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(inspect(rows, 9, 10, True), 3)
        text = output.getvalue()
        self.assertIn("8-10 ", text)
        self.assertIn("9-9 ", text)
        self.assertIn("10-10 ", text)
        self.assertIn("channel=21 dlci=42 device->phone RACE 0x1234", text)
        self.assertIn(reply.hex(" "), text)

    @unittest.skipUnless(shutil.which("tshark"), "requires optional TShark")
    def test_android_snoop_through_tshark(self):
        # H4 ACL records: establish an L2CAP RFCOMM session, then exchange UIH data.
        sent = bytes.fromhex("055a0300341201")
        received = bytes.fromhex("055b0300341202")
        records = [
            (0, 1, bytes.fromhex("0201040003004000")),  # connect request, PSM 3
            (1, 1, bytes.fromhex("030108004100400000000000")),  # response
            (0, 0x41, bytes([0xAB, 0xEF, 1 + 2 * len(sent)]) + sent + b"\x00"),
            (1, 0x40, bytes([0xA9, 0xEF, 1 + 2 * len(received)]) + received + b"\x00"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            capture = Path(tmp) / "btsnoop_hci.log"
            with capture.open("wb") as out:
                out.write(b"btsnoop\x00" + struct.pack(">II", 1, 1002))
                for i, (side, cid, payload) in enumerate(records):
                    l2cap = struct.pack("<HH", len(payload), cid) + payload
                    acl = b"\x02" + struct.pack("<HH", 0x2001, len(l2cap)) + l2cap
                    out.write(struct.pack(">IIIIQ", len(acl), len(acl), side, 0, 0x00E03AB44A676000 + i))
                    out.write(acl)
            result = subprocess.run([
                sys.executable, "-m", "scripts.inspect_eq_capture", str(capture),
                "--handle", "0x1", "--channel", "21", "--hex",
            ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("3-3 ", result.stdout)
        self.assertIn("4-4 ", result.stdout)
        self.assertIn("device->phone RACE 0x1234", result.stdout)
        self.assertIn("phone->device RACE 0x1234", result.stdout)

"""Show the RACE exchange in an Android HCI snoop capture using TShark."""

import argparse
import re
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from scripts.individual_eq import RaceStream, band_gains, describe
from scripts.individual_eq_dsp import generate_curve_dsp, peak_headroom_hundredths, slider_from_hundredths


FIELDS = (
    "frame.number", "frame.interface_id", "bthci_acl.chandle", "bthci_acl.connect_in",
    "btl2cap.connect_in", "btrfcomm.dlci", "btrfcomm.frame_type", "hci_h4.direction",
    "bthci_acl.src.bd_addr", "bthci_acl.dst.bd_addr", "btrfcomm.len", "btspp.data",
)


@dataclass(frozen=True)
class Link:
    interface: str
    handle: int
    acl_start: str
    l2cap_start: str
    dlci: int


class DspVerification:
    def __init__(self):
        self.pending = {}
        self.curves = set()
        self.pairs = 0
        self.mixed_pairs = 0

    def finish_link(self, link):
        if link in self.pending:
            number, _ = self.pending[link]
            raise ValueError(f"Frame {number}: 0x0E2B has no following 0x0E03 on the same connection")

    def observe(self, number, link, message):
        command = int.from_bytes(message[4:6], "little")
        if command != 0x0E03:
            self.finish_link(link)
            if command == 0x0E2B:
                if len(message) != 199 or message[:2] != b"\x05\x5a":
                    raise ValueError(f"Frame {number}: unexpected 0x0E2B request")
                self.pending[link] = (number, message)
            return
        if link not in self.pending:
            raise ValueError(f"Frame {number}: 0x0E03 has no preceding 0x0E2B on the same connection")
        start, params = self.pending.pop(link)
        if len(message) != 451 or message[:2] != b"\x05\x5a" or message[6] != 0:
            raise ValueError(f"Frame {number}: unexpected 0x0E03 request")
        sliders = tuple(slider_from_hundredths(g) for g in band_gains(params, 13))
        order = tuple(struct.unpack_from("<H", message, 11 + 110 * i)[0] for i in range(4))
        expected = generate_curve_dsp(sliders, rate_order=order)
        for offset, (actual, wanted) in enumerate(zip(message[7:], expected, strict=True)):
            if actual != wanted:
                raise ValueError(f"Frames {start}/{number}, sliders {sliders}: DSP byte {offset} "
                                 f"is {actual:#04x} in capture, generator produced {wanted:#04x}")
        peak = peak_headroom_hundredths(sliders)
        recorded = struct.unpack_from("<ii", params, 191)
        if recorded != (peak, peak):
            raise ValueError(f"Frame {start}, sliders {sliders}: captured headroom {recorded}, "
                             f"generator produced {(peak, peak)}")
        self.curves.add(sliders)
        self.pairs += 1
        if sum(position != 50 for position in sliders) >= 2:
            self.mixed_pairs += 1

    def report(self):
        for link in self.pending:
            self.finish_link(link)
        if not self.pairs:
            raise ValueError("No complete outgoing 0x0E2B/0x0E03 pairs found")
        print(f"Verified {self.pairs} DSP blocks and headroom values byte-for-byte, "
              f"{len(self.curves)} distinct curves, {self.mixed_pairs} mixed pairs.")


def print_message(start, end, prefix, message, show_hex):
    try:
        description = describe(message)
    except ValueError as exc:
        # Keep the original bytes for variants of known commands.
        cmd = int.from_bytes(message[4:6], "little")
        description = f"RACE 0x{cmd:04X} type={message[1]:#04x} ({len(message)} bytes) {exc}"
    print(f"{start}-{end} {prefix} {description}")
    if show_hex:
        print("   ", message.hex(" "))


def inspect(rows, first_frame, last_frame, show_hex, *, verify_dsp=False):
    streams = {}
    verification = DspVerification() if verify_dsp else None
    count = 0
    for line in rows:
        (number, interface, handle, acl_start, l2cap_start, dlci, frame_type,
         direction, src, dst, size, raw) = line.rstrip("\r\n").split("\t")
        number = int(number)
        link = Link(interface, int(handle, 0), acl_start, l2cap_start, int(dlci, 0))
        if int(frame_type, 0) in (0x2F, 0x0F, 0x43):  # open, disconnected mode, close
            if verification:
                verification.finish_link(link)
            for side in (0, 1):
                incomplete = streams.pop((link, side), None)
                if verification and incomplete:
                    raise ValueError(f"Frame {number}: partial RACE message from frame {incomplete[1]}")
            continue
        if not int(size, 0):
            continue
        if not direction or int(direction, 0) not in (0, 1):
            raise ValueError(f"Frame {number} has no HCI direction. Use an Android H4 snoop capture.")
        side = int(direction, 0)
        key = (link, side)
        payload = bytes.fromhex(raw.replace(":", ""))
        if len(payload) != int(size, 0):
            raise ValueError(f"Frame {number} has truncated or missing RFCOMM data.")
        if key not in streams:
            if payload[0] not in (0x05, 0x15):
                continue  # Other RFCOMM protocol, or capture started mid-message.
            streams[key] = (RaceStream(), number)
        stream, start = streams[key]
        prefix = (f"peer={(src if side else dst) or '?'} handle={link.handle:#x} "
                  f"channel={link.dlci >> 1} dlci={link.dlci} "
                  f"{'device->phone' if side else 'phone->device'}")
        try:
            for message in stream.feed(payload):
                if number >= first_frame and (last_frame is None or start <= last_frame):
                    if verification:
                        if side == 0:
                            verification.observe(start, link, message)
                    else:
                        print_message(start, number, prefix, message, show_hex)
                    count += 1
                start = number
        except ValueError as exc:
            if verification:
                raise
            print(f"Frames {start}-{number} {prefix}: {exc}", file=sys.stderr)
            del streams[key]
            continue
        if stream.buffer:
            streams[key] = (stream, start)
        else:
            del streams[key]
    for (link, side), (stream, start) in streams.items():
        message = (f"Incomplete message from frame {start}, handle={link.handle:#x} "
                   f"dlci={link.dlci} direction={side} ({len(stream.buffer)} bytes)")
        if verification:
            raise ValueError(message)
        print(message, file=sys.stderr)
    if verification:
        verification.report()
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="btsnoop H4 or an equivalent pcap/pcapng file")
    parser.add_argument("--tshark", default="tshark", help="path to the TShark executable")
    parser.add_argument("--peer", help="Classic Bluetooth MAC address")
    parser.add_argument("--handle", type=lambda s: int(s, 0), help="HCI connection handle")
    parser.add_argument("--channel", type=int, choices=range(1, 31), metavar="1..30")
    parser.add_argument("--first-frame", type=int, default=1)
    parser.add_argument("--last-frame", type=int)
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--hex", action="store_true", help="include full RACE message bytes")
    display.add_argument("--verify-dsp", action="store_true",
                         help="verify each outgoing EQ coefficient block and headroom against the slider gains")
    args = parser.parse_args()
    if args.first_frame < 1 or (args.last_frame is not None and args.last_frame < args.first_frame):
        parser.error("invalid frame interval")
    filters = ["btrfcomm.dlci > 0"]
    if args.peer:
        if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", args.peer):
            parser.error("expected a MAC address such as AA:BB:CC:DD:EE:FF")
        filters.append(f"(bthci_acl.src.bd_addr == {args.peer} || bthci_acl.dst.bd_addr == {args.peer})")
    if args.handle is not None:
        filters.append(f"bthci_acl.chandle == {args.handle}")
    if args.channel is not None:
        filters.append(f"btrfcomm.channel == {args.channel}")
    command = [
        args.tshark, "-2", "-n", "-r", str(args.capture),
        "-d", "btrfcomm.dlci==1-63,btspp", "-Y", " && ".join(filters), "-T", "fields",
    ]
    for field in FIELDS:
        command.extend(["-e", field])
    try:
        with subprocess.Popen(command, stdout=subprocess.PIPE, text=True, encoding="utf-8") as proc:
            try:
                count = inspect(proc.stdout, args.first_frame, args.last_frame, args.hex, verify_dsp=args.verify_dsp)
            finally:
                proc.stdout.close()
            if proc.wait():
                return 1
    except FileNotFoundError:
        parser.exit(1, "TShark executable not found. Install Wireshark or specify --tshark PATH.\n")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Capture inspection failed: {exc}\n")
    if not count:
        parser.exit(2, "No complete RACE messages matched. Include the RFCOMM connection setup in the capture.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Generate Major V Individual EQ coefficients from the five slider positions."""

import argparse
import cmath
import hashlib
import math
import struct
from pathlib import Path

from scripts.individual_eq import BANDS, REFERENCE_DB


SAMPLE_RATES = {1: 44100, 2: 48000, 5: 88200, 6: 96000}
RATE_ORDER = (5, 1, 2, 6)
LEGACY_RATE_ORDER = (1, 6, 2, 5)
QUALITY = (0.7, 0.7, 1.0, 1.0, 1.0)


def _float32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _slider_gain(slider: int) -> float:
    if type(slider) is not int or not 0 <= slider <= 100:
        raise ValueError("Slider position must be an integer in 0..100")
    # The app converts slider positions to dB with binary32 at every step.
    # Keeping that rounding matters at some Q1.23 quantization boundaries.
    fraction = _float32(slider / 100)
    return _float32(_float32(fraction * 12) - 6)


def slider_gain_hundredths(slider: int) -> int:
    """Return the signed hundredths stored in a Major V parameter record."""
    return int(_float32(_slider_gain(slider) * 100))


def slider_from_hundredths(gain: int) -> int:
    """Recover an exact slider position from the vendor's stored gain."""
    if type(gain) is int and -600 <= gain <= 600:
        position = 50 + round(gain / 12)
        if slider_gain_hundredths(position) == gain:
            return position
    raise ValueError(f"Unsupported Individual EQ gain in hundredths: {gain}")


def packed_coefficient(value: float) -> bytes:
    """Signed Q1.23, stored as two little-endian words: high 16, low 8 << 8."""
    integer = max(-(1 << 23), min((1 << 23) - 1, round(value * (1 << 23))))
    return struct.pack("<hH", integer >> 8, (integer & 255) << 8)


def _ordered_bands(sliders):
    if len(sliders) != len(BANDS):
        raise ValueError("Expected five slider positions in 160..6250 Hz band order")
    bands = [(hz, q, _slider_gain(s)) for hz, q, s in zip(BANDS, QUALITY, sliders, strict=True)]
    # Sort by gain, preserving ascending band frequency for tied stages.
    bands.sort(key=lambda band: band[2], reverse=True)
    return bands


def _encode_stages(bands, rate):
    stages = bytearray()
    output_gain = 1.19 / 32
    for i, (frequency, q, gain_db) in enumerate(bands):
        omega = 2 * math.pi * frequency / rate
        alpha = math.sin(omega) / (2 * q)
        amplitude = 10 ** (gain_db / 40)
        numerator = 1 + alpha * amplitude
        denominator = 1 + alpha / amplitude
        scale = 1 / 1.19 if i == 0 else 1.0
        coefficients = (
            scale, -math.cos(omega) / numerator * scale,
            (1 - alpha * amplitude) / numerator * scale,
            -math.cos(omega) / denominator, (1 - alpha / amplitude) / denominator,
        )
        for value in coefficients:
            stages.extend(packed_coefficient(value))
        output_gain *= numerator / denominator
    return stages, output_gain


def generate_curve_dsp(sliders: tuple[int, ...], rate_order: tuple[int, ...] = RATE_ORDER) -> bytes:
    """Produce the 444-byte 0x0E03 block in either captured sample-rate order."""
    if rate_order not in (RATE_ORDER, LEGACY_RATE_ORDER):
        raise ValueError("Unknown Major V DSP sample-rate order")
    bands = _ordered_bands(sliders)
    block = bytearray(struct.pack("<I", len(rate_order)))
    for rate_code in rate_order:
        block.extend(struct.pack("<HHH", rate_code, 53, len(bands)))
        stages, output_gain = _encode_stages(bands, SAMPLE_RATES[rate_code])
        block.extend(stages)
        block.extend(packed_coefficient(output_gain))
    return bytes(block)


def peak_headroom_hundredths(sliders: tuple[int, ...]) -> int:
    """Reproduce the shared L/R peak gain in the capture's 8-byte EF20 record."""
    rate = 44100
    packed, output_gain = _encode_stages(_ordered_bands(sliders), rate)
    words = [(high * 256 + (low >> 8)) / (1 << 23)
             for high, low in struct.iter_unpack("<hH", packed)]
    stages = [words[i:i + 5] for i in range(0, len(words), 5)]
    # The quantized stages and the output gain *before* Q1.23 packing matter.
    # Sampling this response at 4 Hz intervals reproduces both sets of captures.
    peak = 1.0
    for frequency in range(0, rate // 2 + 1, 4):
        z = cmath.exp(-1j * math.tau * frequency / rate)
        z2 = z * z
        magnitude = output_gain * 32
        for b0, b1, b2, a1, a2 in stages:
            magnitude *= abs((b0 + 2 * b1 * z + b2 * z2) / (1 + 2 * a1 * z + a2 * z2))
        peak = max(peak, magnitude)
    return int(2000 * math.log10(peak))


def generate_dsp(slider_160: int) -> bytes:
    """Generate a 160 Hz sweep block in the original capture's section order."""
    return generate_curve_dsp((slider_160, 50, 50, 50, 50), LEGACY_RATE_ORDER)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sliders", type=int, nargs="+", metavar="0..100",
                        help="five positions in band order, or 160 Hz only for the original sweep")
    parser.add_argument("--output", type=Path, help="save the 444-byte DSP block")
    args = parser.parse_args()
    try:
        if len(args.sliders) == 1:
            block = generate_dsp(args.sliders[0])
        else:
            block = generate_curve_dsp(tuple(args.sliders))
        if args.output:
            args.output.write_bytes(block)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"{exc}\n")
    digest = hashlib.sha256(block).hexdigest()
    print(f"SHA-256={digest}")
    if digest in REFERENCE_DB:
        print(f"Matched capture reference for {REFERENCE_DB[digest]:+d} dB at 160 Hz")


if __name__ == "__main__":
    main()

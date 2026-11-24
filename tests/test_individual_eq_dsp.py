import hashlib
import unittest

from scripts.individual_eq_dsp import (
    generate_curve_dsp, generate_dsp, peak_headroom_hundredths, slider_from_hundredths,
    slider_gain_hundredths,
)


# One 0x0E03 observation per distinct 160 Hz slider position in the capture.
# Each digest covers the 444 captured bytes starting at RACE offset 7.
CAPTURED = (
    (0, 8620, "882292ee31f61014b2d678f4b6b728536aef95dfbb44e7ffa8bda5ac6ae4d6b4"),
    (2, 8796, "1f062614287711bfdcb994d23b8ef93c471b9c01c471e89b91df9f96a68266c4"),
    (11, 8612, "336e59e1eacf55ace4b7e6f6753ec0570c0281e2c8b18d9d79cc658305008351"),
    (16, 8804, "b4877134f51de8193784db33fb539871c133166ea9a33e116fd30169b1cd2094"),
    (27, 8814, "4d102bc17340e692cdecaa9bb773921eaa5d255e71c9a8d949fba136dab63db1"),
    (32, 8603, "63f300e3e5da1e8ef72646684f50125ac24e2814531492b2a1404781fadc02da"),
    (34, 8829, "eeee3a4de36aa7e927d93de41cee3185960d05032502361ebe0898c3bd2e7991"),
    (39, 8835, "ccd881264856327ed57f70c2167b39610962bed35b742da810fe229c1ecbe056"),
    (41, 8847, "25d4aff7c334373f4cc9d16d58dbd819a33c6b82a88722764906740f4a27b857"),
    (42, 8860, "2de927d4efc2362753f24a7974f4f99d8cd8898933826eef6ab1ee1c4002cce5"),
    (44, 8868, "ef3fe6b5655de3a664b1f259c2f7c585457f7f504ba2d9fafae45b8441a14596"),
    (46, 8881, "58efa70fc1e7b7413fd995fa0f8379505412529c4e6b232420ba6c588a8b35db"),
    (47, 8889, "e87446d5d27982108b224eba58f0d7fea318e2db3b50178c567805e3353f15f3"),
    (48, 8896, "2356666eb22f2c7b40e217e8b134fe10ee001c5b2b78c21d0883cc7434013c83"),
    (49, 8904, "8bf98a8c2fcdadf9282e303decfac1fd07d7433a7c801d16da9624f690a4a087"),
    (50, 9006, "067f570d21087a60387b0e5238eb63244a97c742ded6d50a5a71cd6d78b56244"),
    (51, 8936, "c6991f8b0e7662c2a401000bc33a71648bc79dab4e5f4f3adf636ec41a3f3dd8"),
    (52, 8929, "d44dbb461d5082ef84f5753cf8947d1f0030bdf2b76001cd77e3a2bfeb1594fb"),
    (53, 8380, "f79ba1f2b45bae60c45eb1c308073764a037f49732cc8c9924c220f3ebd482a8"),
    (61, 8591, "b1869a91b3692404a984019b905aed3363808cb3007a557020a8498f95cf9ead"),
    (69, 8395, "910dface6f410964076a5dbe328e3f0c96e86ca0482aea4cdd5ddbdbbe879bb8"),
    (82, 8583, "20257f62dbc672cb0182d6c0b9f81320afaccaa006b8ddf60f1a52ae59950fb5"),
    (97, 8569, "682e456a1d6218df66d0aaeafe0dc6460838ccfa1209e4fbed95bed6debbb953"),
    (100, 8418, "f429bbdae666c4ba4ab8125f76d34987205438a54efba94d71514f840d10b3d1"),
)


# Independent 0x0E03 digests from majorv-all-bands.log, including quantization
# boundaries and mixed curves with tied gains. The frame numbers identify the source.
ALL_BANDS_CAPTURED = (
    ((50, 50, 50, 50, 50), 26166, "924df94a228db4505f8dbd695e67ed9aa5ca50d9dd3882ddc447efec6ea3f947"),
    ((50, 55, 50, 50, 50), 27903, "5cebac38ed96e59ff2d4f9f78be88f22935c0ce263dbcce2baeac2fb9a50caf9"),
    ((50, 50, 50, 85, 50), 29215, "0e3ca64afb2905297350c0f9f2f9ec904b6a6a7e3bce023fede653ca36624495"),
    ((50, 50, 50, 50, 95), 29929, "7f67b734e8b48aad782b7789e38aec3ea28abddd18bd0e701973f1b47923f028"),
    ((50, 50, 43, 50, 50), 31671, "a9be24f21dec8682278bbacde42eba7ac6159982ceaea9d6e2367b64feeca20e"),
    ((50, 50, 0, 94, 50), 31707, "2cdeeb1fa3e33169980b1a3ddaa1d8fb09cd10d5f85a1db65834827e72d3f84d"),
    ((0, 100, 43, 100, 100), 32980, "01327de46d2885e8ed46b0f8e01441d20913ce6f2f553804be7d2ea5459fd693"),
    ((0, 100, 51, 93, 100), 33210, "16fa8d1b1e92dc8d551338fa627d991a90084edcc0d456801315a85023382f38"),
    ((0, 100, 51, 0, 100), 33248, "1e25cd9f595efe6104e923e6a3abde576493b55d5e00fa5c6b922631df1c0267"),
)


class DspTests(unittest.TestCase):
    def test_generated_blocks_match_captured_hashes(self):
        for position, frame, digest in CAPTURED:
            with self.subTest(slider_160=position, captured_frame=frame):
                dsp = generate_dsp(position)
                self.assertEqual(len(dsp), 444)
                self.assertEqual(hashlib.sha256(dsp).hexdigest(), digest)

    def test_five_band_generator_matches_new_capture(self):
        for positions, frame, digest in ALL_BANDS_CAPTURED:
            with self.subTest(positions=positions, captured_frame=frame):
                block = generate_curve_dsp(positions)
                self.assertEqual(len(block), 444)
                self.assertEqual(hashlib.sha256(block).hexdigest(), digest)

    def test_wire_gain_round_trip(self):
        self.assertEqual(slider_gain_hundredths(51), 11)
        self.assertEqual(slider_gain_hundredths(14), -431)
        for position in range(101):
            self.assertEqual(slider_from_hundredths(slider_gain_hundredths(position)), position)
        for gain in (12, -432, 601, -601, True, 0.0):
            with self.subTest(gain=gain), self.assertRaises(ValueError):
                slider_from_hundredths(gain)

    def test_peak_hundredths_match_captured_stereo_headroom(self):
        # EF20 payloads in the live 0x0E2B messages at the indicated frames.
        for sliders, frame, peak in (
            ((50, 50, 50, 50, 53), 29909, 36),
            ((50, 50, 50, 50, 81), 29922, 372),
            ((50, 50, 50, 50, 95), 29928, 539),
            ((100, 0, 50, 50, 50), 31205, 426),
            ((0, 100, 51, 0, 100), 33247, 506),
        ):
            with self.subTest(sliders=sliders, frame=frame):
                self.assertEqual(peak_headroom_hundredths(sliders), peak)

    def test_requires_five_integer_sliders(self):
        for positions in ((0, 0), (0,) * 6, (0, 50, 101, 50, 50), (50, 50, 50, 50, 50.0)):
            with self.subTest(positions=positions), self.assertRaises(ValueError):
                generate_curve_dsp(positions)

    def test_requires_supported_slider_positions(self):
        for position in (-1, 100.5, 101, True):
            with self.subTest(slider_160=position), self.assertRaises(ValueError):
                generate_dsp(position)

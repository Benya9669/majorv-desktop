"""Exercise the installed bundle independently of the source tree."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def smoke(bundle):
    suffix = ".exe" if sys.platform == "win32" else ""
    with tempfile.TemporaryDirectory() as folder:
        capture = Path(folder, "frame.bin")
        capture.write_bytes(bytes.fromhex("05 5b 03 00 03 0e 00"))
        helper = bundle / ("majorv-eq" + suffix)
        decoded = subprocess.run([helper, "decode", capture], cwd=folder, capture_output=True,
                                 text=True, check=True, timeout=30)
        if "RACE 0x0E03" not in decoded.stdout:
            raise RuntimeError(f"Unexpected helper output: {decoded.stdout!r}")
        invalid = subprocess.run([helper, "read", "00:00:00:00:00:00"], cwd=folder,
                                 capture_output=True, timeout=30)
        if invalid.returncode != 1 or b"Classic Bluetooth MAC address" not in invalid.stderr:
            raise RuntimeError(f"Bluetooth helper failed its offline startup check: {invalid.stderr!r}")
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software",
               "MAJORV_SMOKE_TEST": "1"}
        subprocess.run([bundle / ("majorv-desktop" + suffix), "--demo"],
                       cwd=folder, env=env, timeout=30, check=True)


if __name__ == "__main__":
    smoke(Path(sys.argv[1]).resolve())

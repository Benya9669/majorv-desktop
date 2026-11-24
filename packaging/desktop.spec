from pathlib import Path
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent
assets = root / "majorv/assets"
if sys.platform == "win32":
    # A developer shell can put incompatible ICU/OpenSSL DLLs on PATH via
    # unrelated tools. Resolve Qt/Python wheel dependencies and OS DLLs only.
    windows = Path(os.environ["SystemRoot"])
    python = Path(sys.base_prefix)
    os.environ["PATH"] = os.pathsep.join(map(str, (
        Path(sys.executable).parent, python, python / "DLLs", windows / "System32", windows,
    )))
# Bleak selects the platform backend at runtime. PyWinRT extension modules
# also import their projection modules dynamically.
hidden = collect_submodules("winrt") if sys.platform == "win32" else []
analysis = Analysis(
    [str(root / "packaging/launcher.py")],
    pathex=[str(root)],
    hookspath=[str(root / "packaging/hooks")],
    datas=[
        (str(root / "VERSION"), "."),
        (str(root / "majorv/qml"), "majorv/qml"),
        (str(assets), "majorv/assets"),
    ],
    hiddenimports=hidden,
)
archive = PYZ(analysis.pure)
options = dict(exclude_binaries=True, upx=False)
gui = EXE(
    archive, analysis.scripts, [], name="majorv-desktop", console=False,
    icon=str(assets / "majorv.ico") if sys.platform == "win32" else None,
    **options,
)
helper = EXE(archive, analysis.scripts, [], name="majorv-eq", console=True, **options)
bundle = COLLECT(gui, helper, analysis.binaries, analysis.datas, upx=False, name="majorv-desktop")

"""Entry point for the desktop launcher and its sibling RFCOMM console helper."""

import sys
from pathlib import Path


if Path(sys.executable).stem == "majorv-eq":
    from scripts.individual_eq import main
else:
    from majorv.__main__ import main

sys.exit(main())

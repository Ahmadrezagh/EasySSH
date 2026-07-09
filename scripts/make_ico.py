#!/usr/bin/env python3
"""Create a Windows .ico file from img/logo.png."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    img = root / "img" / "logo.png"
    ico = root / "img" / "logo.ico"

    try:
        from PIL import Image
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pillow", "-q"])
        from PIL import Image

    image = Image.open(img)
    image.save(
        ico,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    print(f"Created {ico}")


if __name__ == "__main__":
    main()

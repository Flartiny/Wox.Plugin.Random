"""Sync plugin source files into dist/ for WPM dev-plugin loading.

Wox's plugin manager only loads dev plugins from the ``dist/`` subdirectory
(it is designed around Node build output and auto-reloads when dist changes).
Python plugins need no compilation, so "building" just means copying the
source files. The no-repeat history (dist/data/) is intentionally preserved.
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist"

FILES = ["plugin.json", "main.py", "generator.py", "storage.py", "presets.py"]
DIRS = ["lang"]


def build() -> None:
    DIST.mkdir(exist_ok=True)
    for name in FILES:
        shutil.copy2(ROOT / name, DIST / name)
    for name in DIRS:
        shutil.copytree(ROOT / name, DIST / name, dirs_exist_ok=True)
    print(f"synced {len(FILES)} files + {len(DIRS)} dirs -> {DIST}")


if __name__ == "__main__":
    build()

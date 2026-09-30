"""构建可发布的 Wox Random 插件包。"""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from build import DIST, build

ROOT = Path(__file__).parent
OUTPUT = ROOT / "wox.plugin.Random.wox"
EXCLUDED_PARTS = {"data", "__pycache__"}


def package() -> None:
    """同步发布文件，并以插件根目录作为归档根目录。"""
    build()

    with ZipFile(OUTPUT, "w", compression=ZIP_DEFLATED) as archive:
        for path in DIST.rglob("*"):
            if not path.is_file() or EXCLUDED_PARTS.intersection(path.relative_to(DIST).parts):
                continue
            archive.write(path, path.relative_to(DIST))

    print(f"packaged {OUTPUT.name}")


if __name__ == "__main__":
    package()

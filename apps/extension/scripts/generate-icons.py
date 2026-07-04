"""Generate square AMO-compliant icons from the source icon."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "icon.png"
SIZES = (16, 48, 128)


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"Missing source icon: {SOURCE}")

    source = Image.open(SOURCE).convert("RGBA")
    width, height = source.size
    side = max(width, height)
    square = Image.new("RGBA", (side, side), (6, 8, 15, 255))
    offset = ((side - width) // 2, (side - height) // 2)
    square.paste(source, offset, source)

    for size in SIZES:
        out = ROOT / f"icon-{size}.png"
        square.resize((size, size), Image.Resampling.LANCZOS).save(out, format="PNG")
        print(f"[generate-icons] Wrote {out.name} ({size}x{size})")

    # Default action icon — 128px square
    square.resize((128, 128), Image.Resampling.LANCZOS).save(ROOT / "icon.png", format="PNG")
    print("[generate-icons] Updated icon.png to 128x128 square")


if __name__ == "__main__":
    main()

from pathlib import Path
from PIL import Image, ImageOps
import argparse


ROOT = Path(__file__).resolve().parent
ORIGINALS = ROOT / "originals"

ORIGINALS.mkdir(exist_ok=True)


def unique_path(path):
    if not path.exists():
        return path

    n = 2

    while True:
        candidate = (
            path.parent
            /
            f"{path.stem}_{n:02d}{path.suffix}"
        )

        if not candidate.exists():
            return candidate

        n += 1


def convert(path):

    path = Path(path)

    if not path.exists():
        print(f"✕ No existe: {path}")
        return

    try:
        image = Image.open(path)
        image = ImageOps.exif_transpose(image)

        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGB")

        output = ORIGINALS / f"{path.stem}.webp"

        output = unique_path(output)

        image.save(
            output,
            "WEBP",
            quality=95,
            method=6
        )

        print(
            f"✓ {path}"
            f"\n  → {output}"
        )

    except Exception as e:
        print(f"✕ {path} / {e}")


parser = argparse.ArgumentParser()

parser.add_argument(
    "images",
    nargs="+",
    help="Raw images to copy/convert into originals/"
)

args = parser.parse_args()


for image in args.images:
    convert(image)
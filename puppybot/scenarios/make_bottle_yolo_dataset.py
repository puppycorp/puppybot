#!/usr/bin/env python3
"""Create a small, reproducible RobotDreams RGB training set for YOLO.

The source frame must come from the named simulation camera.  Its crop bounds
are deliberately recorded here rather than inferred by the runtime policy:
these labels are offline training data only; episode-time perception remains
the exported YOLO model operating on the live camera PNG.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from PIL import Image


# Pixel bounds of the bottle in the canonical, camera-aligned source frame.
# They are an offline annotation, not a runtime heuristic.
DEFAULT_BOTTLE_BOX = (296, 226, 346, 254)


def label_line(box: tuple[int, int, int, int], width: int, height: int) -> str:
    left, top, right, bottom = box
    return "0 {:.6f} {:.6f} {:.6f} {:.6f}\n".format(
        (left + right) / (2 * width),
        (top + bottom) / (2 * height),
        (right - left) / width,
        (bottom - top) / height,
    )


def foreground_mask(crop: Image.Image) -> Image.Image:
    """Keep the light-blue bottle pixels while making the floor transparent."""
    rgba = crop.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            red, green, blue, _ = pixels[x, y]
            # The exported bottle is cyan/light-blue.  This prepares labels
            # for augmentation only and is never used by the autonomy policy.
            alpha = 255 if blue > 135 and blue > red * 1.15 and blue > green * 0.95 else 0
            pixels[x, y] = (red, green, blue, alpha)
    return rgba


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-frame", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=160)
    parser.add_argument("--seed", type=int, default=20260718)
    parser.add_argument("--prefix", default="bottle", help="filename prefix, useful when appending another camera pose")
    parser.add_argument("--append", action="store_true", help="append examples to an existing compatible dataset")
    parser.add_argument("--box", type=int, nargs=4, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"),
                        default=DEFAULT_BOTTLE_BOX, help="offline bottle annotation in the source frame")
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()) and not args.append:
        raise RuntimeError("refusing to overwrite a non-empty dataset directory")

    source = Image.open(args.source_frame).convert("RGB")
    width, height = source.size
    bottle_box = tuple(args.box)
    left, top, right, bottom = bottle_box
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise RuntimeError("--box must lie inside the source frame")
    crop = foreground_mask(source.crop(bottle_box))
    images = args.output / "images"
    labels = args.output / "labels"
    images.mkdir(parents=True, exist_ok=True)
    labels.mkdir(exist_ok=True)
    rng = random.Random(args.seed)
    for index in range(args.count):
        frame = source.copy()
        lines = [label_line(bottle_box, width, height)]
        if index:
            scale = rng.uniform(0.78, 1.24)
            patch = crop.resize((round(crop.width * scale), round(crop.height * scale)))
            left = rng.randrange(245, 405 - patch.width)
            top = rng.randrange(150, 350 - patch.height)
            frame.paste(patch, (left, top), patch)
            lines.append(label_line((left, top, left + patch.width, top + patch.height), width, height))
        stem = f"{args.prefix}-{index:04d}"
        frame.save(images / f"{stem}.png")
        (labels / f"{stem}.txt").write_text("".join(lines), encoding="utf-8")
    (args.output / "data.yaml").write_text(
        f"path: {args.output}\ntrain: images\nval: images\nnames:\n  0: bottle\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

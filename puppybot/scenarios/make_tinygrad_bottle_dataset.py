#!/usr/bin/env python3
"""Build a reproducible, labelled TCP-RGB bootstrap dataset for Tinygrad.

The input is a RobotDreams wrist-camera PNG and ``--box`` is its *offline*
annotation.  This tool is deliberately not imported by the autonomy policy:
the synthetic labels and the colour/foreground mask used to place the rendered
bottle exist only while creating the training corpus.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from PIL import Image


# Offline annotation of the current canonical RobotDreams TCP capture.  This
# is deliberately separate from the old YOLO bootstrap annotation, which was
# for a different camera framing.
DEFAULT_BOTTLE_BOX = (214, 285, 317, 326)


def label(box: tuple[int, int, int, int], width: int, height: int) -> dict[str, float]:
    left, top, right, bottom = box
    return {
        "left": left / width,
        "top": top / height,
        "right": right / width,
        "bottom": bottom / height,
    }


def bottle_mask(source: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    """Extract the known rendered bottle for offline augmentation only."""
    crop = source.crop(box).convert("RGBA")
    pixels = crop.load()
    for y in range(crop.height):
        for x in range(crop.width):
            red, green, blue, _ = pixels[x, y]
            # This is a corpus-construction matte, never policy-time logic.
            alpha = 255 if blue > 135 and blue > red * 1.15 and blue > green * 0.95 else 0
            pixels[x, y] = (red, green, blue, alpha)
    return crop


def erase_box(image: Image.Image, box: tuple[int, int, int, int]) -> None:
    """Replace the annotated object with nearby floor pixels in the corpus only."""
    left, top, right, bottom = box
    width = right - left
    donor_left = min(image.width - width, right + 12)
    donor = image.crop((donor_left, top, donor_left + width, bottom))
    image.paste(donor, (left, top))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-frame", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--seed", type=int, default=20260718)
    parser.add_argument("--validation-fraction", type=float, default=0.2)
    parser.add_argument("--box", type=int, nargs=4, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"),
                        default=DEFAULT_BOTTLE_BOX)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise RuntimeError("refusing to overwrite a non-empty dataset directory")
    if args.count < 20 or not 0.05 <= args.validation_fraction < 0.5:
        raise RuntimeError("need at least 20 frames and validation fraction in [0.05, 0.5)")

    source = Image.open(args.source_frame).convert("RGB")
    width, height = source.size
    source_box = tuple(args.box)
    left, top, right, bottom = source_box
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise RuntimeError("--box must be inside the simulator frame")
    patch = bottle_mask(source, source_box)
    clean = source.copy()
    erase_box(clean, source_box)
    args.output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    rows: list[dict[str, object]] = []
    for index in range(args.count):
        frame = clean.copy()
        # One fifth are true negative simulator-floor images.  The rest place
        # a rendered bottle over the simulator frame at varied scales/poses.
        has_bottle = index % 5 != 0
        box: tuple[int, int, int, int] | None = None
        if has_bottle:
            scale = rng.uniform(0.65, 1.45)
            resized = patch.resize((max(8, round(patch.width * scale)), max(8, round(patch.height * scale))))
            x = rng.randrange(18, width - resized.width - 18)
            y = rng.randrange(80, height - resized.height - 18)
            frame.paste(resized, (x, y), resized)
            box = (x, y, x + resized.width, y + resized.height)
        # A deterministic but decorrelated split: do not make validation a
        # subset of the every-fifth negative-frame cadence above.
        split = "val" if (index * 37 + 11) % 100 < round(args.validation_fraction * 100) else "train"
        filename = f"{split}-{index:04d}.png"
        frame.save(args.output / filename)
        rows.append({"image": filename, "split": split, "box": None if box is None else label(box, width, height)})
    manifest = {
        "schema": "puppybot.tinygrad-bottle-dataset.v1",
        "source": str(args.source_frame),
        "sourceAnnotation": {"boxPixels": list(source_box), "purpose": "offline simulator label only"},
        "seed": args.seed,
        "imageSize": [width, height],
        "count": args.count,
        "rows": rows,
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "train": sum(r["split"] == "train" for r in rows),
                      "val": sum(r["split"] == "val" for r in rows)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

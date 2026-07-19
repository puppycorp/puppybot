#!/usr/bin/env python3
"""Build the all-state, source-disjoint V6 Tinygrad corpus (offline only)."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from PIL import Image

def split(source: str) -> str:
    # A source is a single immutable simulator state. Derivatives never cross.
    bucket = int(hashlib.sha256(source.encode()).hexdigest()[:8], 16) % 10
    return "test" if bucket == 0 else "validation" if bucket in (1, 2) else "train"

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()): raise RuntimeError("refusing non-empty output")
    captures = []
    for manifest_path in sorted(args.captures.glob("**/manifest.json")):
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("schema") != "puppybot.training-only.tcp-dataset.v4": continue
        row = manifest.get("frame") or (manifest.get("frames") or [None])[0]
        if not isinstance(row, dict) or not isinstance(row.get("bottleMask"), str): continue
        image, mask = manifest_path.parent / row["image"], manifest_path.parent / row["bottleMask"]
        if image.is_file() and mask.is_file(): captures.append((manifest_path.parent.name, image, mask, row["label"]["xyxy"]))
    if len(captures) != 55: raise RuntimeError(f"expected exactly 55 V4 base states, found {len(captures)}")
    args.output.mkdir(parents=True); rows = []
    for index, (source, image_path, mask_path, box) in enumerate(captures):
        part = split(source); image = Image.open(image_path).convert("RGB"); mask = Image.open(mask_path).convert("L")
        positive = f"{part}-base-{index:03d}.png"; image.save(args.output / positive); (args.output / f"{positive}.mask.png").write_bytes(mask_path.read_bytes())
        rows.append({"image": positive, "mask": f"{positive}.mask.png", "split": part, "baseState": source, "kind": "positive", "box": box})
        negative = image.copy(); negative.paste((8, 18, 28), mask=mask)
        negative_name = f"{part}-base-{index:03d}-negative.png"; negative.save(args.output / negative_name)
        rows.append({"image": negative_name, "split": part, "baseState": source, "kind": "true-negative", "box": None})
    report = {"schema": "puppybot.tinygrad-bottle-corpus.v6", "offlineOnly": True,
              "labelProvenance": "V4 exact rendered silhouette masks; unavailable to autonomy",
              "split": "SHA256 base-state split before positive/negative derivation; no source crosses splits",
              "rows": rows}
    (args.output / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    counts = {part: sum(row["split"] == part for row in rows) for part in ("train", "validation", "test")}
    print(json.dumps({"baseStates": len(captures), "rows": len(rows), **counts}))
    return 0
if __name__ == "__main__": raise SystemExit(main())

#!/usr/bin/env python3
"""Combine V4 captures from independent scenes into a source-disjoint V7 corpus."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from PIL import Image

def split(key: str) -> str:
    bucket = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % 10
    return "test" if bucket == 0 else "validation" if bucket in (1, 2) else "train"

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--captures", type=Path, required=True); parser.add_argument("--output", type=Path, required=True); parser.add_argument("--minimum-base-states", type=int, default=80)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()): raise RuntimeError("refusing non-empty output")
    captures = []
    for manifest_path in sorted(args.captures.glob("**/manifest.json")):
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("schema") != "puppybot.training-only.tcp-dataset.v4": continue
        row = manifest.get("frame") or (manifest.get("frames") or [None])[0]
        if not isinstance(row, dict) or not isinstance(row.get("bottleMask"), str): continue
        source = str(manifest_path.parent.relative_to(args.captures))
        # A scene root is accepted only when produced by the bounded quick
        # grid. This excludes partial candidate directories left by aborted
        # broad-grid attempts.
        if "/" not in source or not source.split("/", 1)[0].endswith("-quick"): continue
        image, mask = manifest_path.parent / row["image"], manifest_path.parent / row["bottleMask"]
        if image.is_file() and mask.is_file(): captures.append((source, image, mask, row["label"]["xyxy"]))
    if len(captures) < args.minimum_base_states: raise RuntimeError(f"need {args.minimum_base_states} independent V4 base states; found {len(captures)}")
    scenes = sorted({source.split("/", 1)[0] for source, *_ in captures})
    if len(scenes) < 3: raise RuntimeError(f"need at least three independent scenes; found {len(scenes)}")
    scene_split = {scene: ("train" if index % 3 == 0 else "validation" if index % 3 == 1 else "test") for index, scene in enumerate(scenes)}
    args.output.mkdir(parents=True); rows = []
    for index, (source, image_path, mask_path, box) in enumerate(captures):
        part = scene_split[source.split("/", 1)[0]]; image = Image.open(image_path).convert("RGB"); mask = Image.open(mask_path).convert("L")
        positive = f"{part}-base-{index:04d}.png"; image.save(args.output / positive); (args.output / f"{positive}.mask.png").write_bytes(mask_path.read_bytes())
        rows.append({"image": positive, "mask": f"{positive}.mask.png", "split": part, "baseState": source, "kind": "positive", "box": box})
        negative = image.copy(); negative.paste((8, 18, 28), mask=mask); name = f"{part}-base-{index:04d}-negative.png"; negative.save(args.output / name)
        rows.append({"image": name, "split": part, "baseState": source, "kind": "true-negative", "box": None})
    report = {"schema": "puppybot.tinygrad-bottle-corpus.v6", "offlineOnly": True, "labelProvenance": "V4 exact silhouette masks across independent scene seeds; unavailable to autonomy", "split": "entire deterministic scene assigned to train/validation/test before derivation; no scene crosses splits", "sceneSplit": scene_split, "rows": rows}
    (args.output / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"baseStates": len(captures), "rows": len(rows), **{part: sum(row["split"] == part for row in rows) for part in ("train", "validation", "test")}}))
    return 0
if __name__ == "__main__": raise SystemExit(main())

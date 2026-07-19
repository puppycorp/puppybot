#!/usr/bin/env python3
"""Assemble varied, offline-labelled TCP frames from recorded simulator episodes.

This tool is deliberately outside autonomy.  It consumes saved wrist PNGs and
their archived offline detection records; the policy never reads this corpus.
Episodes, rather than adjacent frames, are deterministically split to avoid
near-duplicate train/validation leakage.  Records are *weak labels* and the
manifest says so; they are a data-expansion baseline, not simulator truth.
"""
from __future__ import annotations

import argparse, hashlib, json
from pathlib import Path
from PIL import Image

def split_for_key(key: str) -> str:
    return "val" if int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % 5 == 0 else "train"

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--recordings", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists() and any(a.output.iterdir()): raise RuntimeError("refusing non-empty output")
    a.output.mkdir(parents=True, exist_ok=True)
    rows, seen = [], set()
    for log in sorted(a.recordings.glob("**/tcp-yolo-detections.jsonl")):
      episode = str(log.parent.parent if log.parent.name == "policy" else log.parent)
      for line in log.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        image_path = log.parent / event["image"]
        if not image_path.is_file() or str(image_path) in seen: continue
        seen.add(str(image_path)); image = Image.open(image_path).convert("RGB")
        out = f"{len(rows):04d}.png"; image.save(a.output / out)
        detection = event.get("detection"); box = None
        if isinstance(detection, dict):
          left, top, right, bottom = detection["xyxy"]; width, height = image.size
          box = {"left": left/width, "top": top/height, "right": right/width, "bottom": bottom/height}
        rows.append({"image": out, "split": split_for_key(f"{episode}/{event['image']}"), "box": box,
                     "episode": episode, "phase": event["phase"]})
    manifest = {"schema":"puppybot.tinygrad-bottle-dataset.v1", "labelProvenance":"offline archived weak labels; never runtime input",
                "split":"frame-path hash modulo 5 (deterministic; source episodes remain listed)", "rows":rows}
    (a.output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({"frames":len(rows), "train":sum(r["split"]=="train" for r in rows), "val":sum(r["split"]=="val" for r in rows),
                      "positives":sum(r["box"] is not None for r in rows), "negatives":sum(r["box"] is None for r in rows)}, sort_keys=True))
    return 0
if __name__ == "__main__": raise SystemExit(main())

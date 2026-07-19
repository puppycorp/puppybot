#!/usr/bin/env python3
"""Build an offline Tinygrad corpus from V4 simulator silhouette captures.

Splits are assigned to the *base simulator state* before any derived sample is
made.  This tool never imports or serves autonomy code.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from PIL import Image

def split(key: str) -> str:
    return "heldout" if int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % 5 == 0 else "train"

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--captures", type=Path, required=True, help="directory containing V4 capture directories")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--base-states", type=int, default=24)
    a=p.parse_args()
    if a.output.exists() and any(a.output.iterdir()): raise RuntimeError("refusing non-empty output")
    captures=[]
    for manifest in sorted(a.captures.glob("**/manifest.json")):
        data=json.loads(manifest.read_text())
        if data.get("schema")!="puppybot.training-only.tcp-dataset.v4": continue
        # A grid candidate manifest contains one ``frame``; a capture root
        # contains the historical one-element ``frames`` array.  Accept both
        # V4 forms while retaining exactly one labelled base state per source.
        row=data.get("frame")
        if row is None:
            frames=data.get("frames", [])
            row=frames[0] if frames else None
        if row is None: continue
        if "bottleMask" not in row: continue
        image=manifest.parent/row["image"]; mask=manifest.parent/row["bottleMask"]
        if image.is_file() and mask.is_file(): captures.append((manifest.parent.name, image, mask, row["label"]["xyxy"]))
    if not captures: raise RuntimeError("no V4 silhouette-mask captures found")
    a.output.mkdir(parents=True); rows=[]
    if len(captures) < a.base_states:
        raise RuntimeError(f"need {a.base_states} unique V4 base states; found {len(captures)}")
    for i, (source,image_path,mask_path,box) in enumerate(captures[:a.base_states]):
        key=source; part=split(key)
        image=Image.open(image_path).convert("RGB"); mask=Image.open(mask_path).convert("L")
        positive=f"{part}-base-{i:03d}.png"; image.save(a.output/positive); (a.output/f"{positive}.mask.png").write_bytes(mask_path.read_bytes())
        rows.append({"image":positive,"mask":f"{positive}.mask.png","split":part,"baseState":key,"kind":"positive","box":box})
        # True negative: erase the labelled rendered silhouette with dark floor
        # only inside the mask; it contains no bottle pixels and keeps arm/floor.
        negative=image.copy(); negative.paste((8,18,28), mask=mask)
        name=f"{part}-base-{i:03d}-negative.png"; negative.save(a.output/name)
        rows.append({"image":name,"split":part,"baseState":key,"kind":"true-negative","box":None})
    manifest={"schema":"puppybot.tinygrad-bottle-corpus.v3","offlineOnly":True,
      "labelProvenance":"V4 training-only bottle silhouette masks; unavailable to autonomy",
      "split":"base-state SHA256 split before derivation; no source crosses splits",
      "limitation":"no image augmentation is emitted by this base-state builder",
      "rows":rows}
    (a.output/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print(json.dumps({"baseStates":a.base_states,"uniqueSources":len(captures),"rows":len(rows)}))
    return 0
if __name__=="__main__": raise SystemExit(main())

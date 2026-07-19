#!/usr/bin/env python3
"""Native Tinygrad one-class TCP bottle detector.

This deliberately uses Tinygrad through the checked-in ``examples/tinygrad``
submodule.  It is not YOLO, not an ONNX runner, and never reads simulator
scene state at inference time. The model has explicit objectness trained on
both positive and true-negative frames, plus a normalized box-regression head
trained only where a bottle exists.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


INPUT_SIZE = (160, 120)  # Width, height. A native 1-class detector, not YOLO/ONNX.


def tinygrad_imports() -> tuple[Any, Any, Any, Any, Any]:
    repo = Path(__file__).resolve().parents[2] / "examples" / "tinygrad"
    if not repo.is_dir():
        raise RuntimeError("Tinygrad submodule missing; run git submodule update --init examples/tinygrad")
    os.environ.setdefault("XDG_CACHE_HOME", "/tmp/puppybot-tinygrad-cache")
    import sys
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from tinygrad import Tensor, nn
    from tinygrad.helpers import Context
    from tinygrad.nn.state import get_parameters, get_state_dict, load_state_dict, safe_load, safe_save
    return Tensor, nn, Context, (get_parameters, get_state_dict, load_state_dict, safe_load, safe_save), repo


class BottleObjectBoxNet:
    """Native Tinygrad detector: RGB+XY -> objectness logit and cx/cy/w/h."""
    def __init__(self, nn: Any) -> None:
        # XY lets a global pooled feature retain image location. Without it a
        # translation-equivariant pooled CNN cannot regress an absolute box.
        self.conv1 = nn.Conv2d(5, 12, 3, padding=1)
        self.conv2 = nn.Conv2d(12, 12, 3, padding=1)
        self.objectness = nn.Linear(12, 1)
        self.box = nn.Linear(12, 4)

    def __call__(self, x: Any) -> Any:
        features = self.conv2(self.conv1(x).relu()).relu()
        pooled = features.mean(axis=(2, 3))
        return self.objectness(pooled), self.box(pooled).sigmoid()


def load_manifest(dataset: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") not in {
        "puppybot.tinygrad-bottle-dataset.v1",
        "puppybot.tinygrad-bottle-corpus.v3",
        "puppybot.tinygrad-bottle-corpus.v6",
    }:
        raise RuntimeError("unexpected Tinygrad bottle dataset schema")
    rows = manifest.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError("dataset rows missing")
    return manifest, rows


def batch(dataset: Path, rows: list[dict[str, Any]], indices: list[int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    width, height = INPUT_SIZE
    images, objects, boxes = [], [], []
    xs = np.linspace(-1.0, 1.0, width, dtype=np.float32)[None, :].repeat(height, axis=0)
    ys = np.linspace(-1.0, 1.0, height, dtype=np.float32)[:, None].repeat(width, axis=1)
    for index in indices:
        row = rows[index]
        image = Image.open(dataset / row["image"]).convert("RGB").resize(INPUT_SIZE)
        rgb = np.asarray(image, dtype=np.float32).transpose(2, 0, 1) / 255.0
        mask = np.zeros((height, width), dtype=np.float32)
        # V3 has an exact rendered silhouette.  Prefer it to a rectangle so
        # training and evaluation never silently turn the offline truth mask
        # into a weak bounding-box label.
        if isinstance(row.get("mask"), str):
            mask_image = Image.open(dataset / row["mask"]).convert("L").resize(INPUT_SIZE)
            mask = (np.asarray(mask_image, dtype=np.float32) > 127.0).astype(np.float32)
        box = row.get("box")
        if not mask.any() and isinstance(box, dict):
            left, top = round(float(box["left"]) * width), round(float(box["top"]) * height)
            right, bottom = round(float(box["right"]) * width), round(float(box["bottom"]) * height)
            mask[max(0, top):min(height, bottom), max(0, left):min(width, right)] = 1.0
        if mask.any():
            y, x = np.where(mask > 0.5)
            left, top = x.min() / width, y.min() / height
            right, bottom = (x.max() + 1) / width, (y.max() + 1) / height
            boxes.append([(left + right) / 2.0, (top + bottom) / 2.0, right - left, bottom - top])
            objects.append(1.0)
        else:
            boxes.append([0.0, 0.0, 0.0, 0.0])
            objects.append(0.0)
        images.append(np.concatenate((rgb, xs[None], ys[None]), axis=0))
    return np.stack(images), np.asarray(objects, dtype=np.float32)[:, None], np.asarray(boxes, dtype=np.float32)


def iou_cxcywh(truth: np.ndarray, predicted: np.ndarray) -> float:
    tx1, ty1 = truth[0] - truth[2] / 2.0, truth[1] - truth[3] / 2.0
    tx2, ty2 = truth[0] + truth[2] / 2.0, truth[1] + truth[3] / 2.0
    px1, py1 = predicted[0] - predicted[2] / 2.0, predicted[1] - predicted[3] / 2.0
    px2, py2 = predicted[0] + predicted[2] / 2.0, predicted[1] + predicted[3] / 2.0
    intersection = max(0.0, min(tx2, px2) - max(tx1, px1)) * max(0.0, min(ty2, py2) - max(ty1, py1))
    truth_area = max(0.0, tx2 - tx1) * max(0.0, ty2 - ty1)
    predicted_area = max(0.0, px2 - px1) * max(0.0, py2 - py1)
    return float(intersection / max(truth_area + predicted_area - intersection, 1e-9))


def evaluate(model: BottleObjectBoxNet, Tensor: Any, Context: Any, dataset: Path, rows: list[dict[str, Any]], threshold: float) -> dict[str, float]:
    # Legacy V1 calls this validation; V3 calls the independent base-state
    # partition heldout.  Never evaluate on train when the split is missing.
    eval_split = "val" if any(row["split"] == "val" for row in rows) else "heldout"
    candidates = [index for index, row in enumerate(rows) if row["split"] == eval_split]
    if not candidates:
        raise RuntimeError(f"dataset has no {eval_split} evaluation rows")
    correct, false_positive, false_negative, iou_sum = 0, 0, 0, 0.0
    started = time.perf_counter()
    with Context(TRAINING=0):
        for index in candidates:
            image, target_object, target_box = batch(dataset, rows, [index])
            object_logit, predicted_box = model(Tensor(image))
            detected = float(object_logit.sigmoid().numpy()[0, 0]) >= threshold
            truth = bool(target_object[0, 0] > 0.5)
            if truth and detected:
                iou = iou_cxcywh(target_box[0], predicted_box.numpy()[0])
                iou_sum += iou
                correct += int(iou >= 0.5)
            elif truth:
                false_negative += 1
            elif detected:
                false_positive += 1
            else:
                correct += 1
    elapsed = time.perf_counter() - started
    positives = sum(bool(batch(dataset, rows, [index])[1][0, 0] > 0.5) for index in candidates)
    negatives = len(candidates) - positives
    return {"split": eval_split, "frames": int(len(candidates)), "positives": int(positives), "negatives": int(negatives), "correct": int(correct),
            "falsePositive": int(false_positive), "falseNegative": int(false_negative),
            "meanPositiveIoU": float(iou_sum / max(positives - false_negative, 1)),
            "positiveRecall": float((positives - false_negative) / max(positives, 1)),
            "negativeFpr": float(false_positive / max(negatives, 1)),
            "fps": len(candidates) / max(elapsed, 1e-9)}


def train(args: argparse.Namespace) -> int:
    Tensor, nn, Context, state, _ = tinygrad_imports()
    get_parameters, get_state_dict, _, _, safe_save = state
    _, rows = load_manifest(args.dataset)
    train_indices = [index for index, row in enumerate(rows) if row["split"] == "train"]
    if not train_indices:
        raise RuntimeError("dataset has no train rows")
    rng = np.random.default_rng(args.seed)
    model = BottleObjectBoxNet(nn)
    optimizer = nn.optim.Adam(get_parameters(model), lr=args.learning_rate)
    # Explicit objectness sees every true negative. Box regression is masked
    # to positives, so a negative never supplies a fake zero-sized box target.
    history: list[dict[str, float]] = []
    with Context(TRAINING=1):
        for step in range(args.steps):
            selected = rng.choice(train_indices, size=args.batch_size, replace=True).tolist()
            images, target_object, target_box = batch(args.dataset, rows, selected)
            object_logits, predicted_box = model(Tensor(images))
            object_probability = object_logits.sigmoid()
            object_tensor = Tensor(target_object)
            object_loss = -(object_tensor * object_probability.log()
                            + (1.0 - object_tensor) * (1.0 - object_probability).log()).mean()
            box_loss = (((predicted_box - Tensor(target_box)) ** 2) * object_tensor).sum() / max(float(target_object.sum()), 1.0)
            loss = object_loss + box_loss * args.box_weight
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            if (step + 1) % args.report_every == 0 or step == 0:
                history.append({"step": step + 1, "loss": float(loss.numpy()),
                                "objectnessLoss": float(object_loss.numpy()),
                                "boxRegressionLoss": float(box_loss.numpy())})
    args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    safe_save(get_state_dict(model), args.checkpoint)
    metrics = evaluate(model, Tensor, Context, args.dataset, rows, args.threshold)
    result = {"schema": "puppybot.tinygrad-bottle-training.v2", "backend": "native-tinygrad",
              "architecture": "3x3 Conv(5,12) -> 3x3 Conv(12,12) -> global pool -> objectness + cx/cy/w/h",
              "input": [5, INPUT_SIZE[1], INPUT_SIZE[0]], "steps": args.steps, "batchSize": args.batch_size,
              "learningRate": args.learning_rate, "boxWeight": args.box_weight, "threshold": args.threshold,
              "checkpoint": str(args.checkpoint), "history": history, "validation": metrics}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def benchmark(args: argparse.Namespace) -> int:
    Tensor, nn, Context, state, _ = tinygrad_imports()
    _, _, load_state_dict, safe_load, _ = state
    _, rows = load_manifest(args.dataset)
    model = BottleObjectBoxNet(nn)
    load_state_dict(model, safe_load(args.checkpoint))
    image, _, _ = batch(args.dataset, rows, [0])
    with Context(TRAINING=0):
        object_logit, box = model(Tensor(image))
        object_logit.sigmoid().numpy(); box.numpy()  # compiler/cache warm-up
        elapsed = []
        for _ in range(args.runs):
            started = time.perf_counter()
            object_logit, box = model(Tensor(image))
            object_logit.sigmoid().numpy(); box.numpy()
            elapsed.append((time.perf_counter() - started) * 1000.0)
    result = {"runs": args.runs, "meanMs": float(np.mean(elapsed)), "p95Ms": float(np.percentile(elapsed, 95)),
              "meanHz": 1000.0 / max(float(np.mean(elapsed)), 1e-9)}
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def evaluate_checkpoint(args: argparse.Namespace) -> int:
    Tensor, nn, Context, state, _ = tinygrad_imports()
    _, _, load_state_dict, safe_load, _ = state
    _, rows = load_manifest(args.dataset)
    model = BottleObjectBoxNet(nn)
    load_state_dict(model, safe_load(args.checkpoint))
    result = evaluate(model, Tensor, Context, args.dataset, rows, args.threshold)
    result["threshold"] = args.threshold
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    train_parser = commands.add_parser("train")
    train_parser.add_argument("--dataset", type=Path, required=True)
    train_parser.add_argument("--checkpoint", type=Path, required=True)
    train_parser.add_argument("--report", type=Path, required=True)
    train_parser.add_argument("--steps", type=int, default=160)
    train_parser.add_argument("--batch-size", type=int, default=8)
    train_parser.add_argument("--learning-rate", type=float, default=0.003)
    train_parser.add_argument("--box-weight", type=float, default=6.0)
    # Fixed operating point; no threshold is selected from heldout data.
    train_parser.add_argument("--threshold", type=float, default=0.50)
    train_parser.add_argument("--report-every", type=int, default=20)
    train_parser.add_argument("--seed", type=int, default=20260718)
    benchmark_parser = commands.add_parser("benchmark")
    benchmark_parser.add_argument("--dataset", type=Path, required=True)
    benchmark_parser.add_argument("--checkpoint", type=Path, required=True)
    benchmark_parser.add_argument("--runs", type=int, default=20)
    benchmark_parser.add_argument("--report", type=Path)
    eval_parser = commands.add_parser("evaluate")
    eval_parser.add_argument("--dataset", type=Path, required=True)
    eval_parser.add_argument("--checkpoint", type=Path, required=True)
    eval_parser.add_argument("--threshold", type=float, required=True)
    eval_parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.command == "train":
        return train(args)
    if args.command == "benchmark":
        return benchmark(args)
    return evaluate_checkpoint(args)


if __name__ == "__main__":
    raise SystemExit(main())

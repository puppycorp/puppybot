#!/usr/bin/env python3
"""Native Tinygrad V5 spatial-grid TCP bottle detector, offline only.

Unlike the V4 global-pool trial, this keeps spatial evidence through a 30x40
grid. Each cell predicts objectness and a local cx/cy/w/h box. A silhouette
positive supervises exactly its center cell; every other cell, and every cell
in a mask-erased true negative, is an explicit focal-loss negative.
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

from tinygrad_bottle_detector import INPUT_SIZE, load_manifest, tinygrad_imports

GRID_W, GRID_H = 40, 30


class BottleGridNet:
    """3x120x160 RGB -> 5x30x40 (objectness, local cx/cy/w/h)."""
    def __init__(self, nn: Any) -> None:
        self.conv1 = nn.Conv2d(3, 8, 3, stride=2, padding=1)
        self.conv2 = nn.Conv2d(8, 16, 3, stride=2, padding=1)
        self.head = nn.Conv2d(16, 5, 1)

    def __call__(self, image: Any) -> Any:
        return self.head(self.conv2(self.conv1(image).relu()).relu())


def samples(dataset: Path, rows: list[dict[str, Any]], indices: list[int]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    width, height = INPUT_SIZE
    images, present, boxes, object_targets, box_targets = [], [], [], [], []
    for index in indices:
        row = rows[index]
        image = Image.open(dataset / row["image"]).convert("RGB").resize(INPUT_SIZE)
        images.append(np.asarray(image, dtype=np.float32).transpose(2, 0, 1) / 255.0)
        mask = np.zeros((height, width), dtype=np.float32)
        if isinstance(row.get("mask"), str):
            mask = (np.asarray(Image.open(dataset / row["mask"]).convert("L").resize(INPUT_SIZE), dtype=np.float32) > 127.0).astype(np.float32)
        elif isinstance(row.get("box"), dict):
            box = row["box"]
            left, top = round(float(box["left"]) * width), round(float(box["top"]) * height)
            right, bottom = round(float(box["right"]) * width), round(float(box["bottom"]) * height)
            mask[max(0, top):min(height, bottom), max(0, left):min(width, right)] = 1.0
        object_target = np.zeros((1, GRID_H, GRID_W), dtype=np.float32)
        box_target = np.zeros((4, GRID_H, GRID_W), dtype=np.float32)
        if mask.any():
            y, x = np.where(mask > 0.5)
            left, top = x.min() / width, y.min() / height
            right, bottom = (x.max() + 1) / width, (y.max() + 1) / height
            cx, cy, bw, bh = (left + right) / 2.0, (top + bottom) / 2.0, right - left, bottom - top
            cell_x, cell_y = min(int(cx * GRID_W), GRID_W - 1), min(int(cy * GRID_H), GRID_H - 1)
            object_target[0, cell_y, cell_x] = 1.0
            box_target[:, cell_y, cell_x] = [cx * GRID_W - cell_x, cy * GRID_H - cell_y, bw, bh]
            present.append(1.0); boxes.append([cx, cy, bw, bh])
        else:
            present.append(0.0); boxes.append([0.0, 0.0, 0.0, 0.0])
        object_targets.append(object_target); box_targets.append(box_target)
    return (np.stack(images), np.asarray(present, dtype=np.float32), np.asarray(boxes, dtype=np.float32),
            np.stack(object_targets), np.stack(box_targets))


def iou_cxcywh(truth: np.ndarray, predicted: np.ndarray) -> float:
    tx1, ty1, tx2, ty2 = truth[0] - truth[2] / 2, truth[1] - truth[3] / 2, truth[0] + truth[2] / 2, truth[1] + truth[3] / 2
    px1, py1, px2, py2 = predicted[0] - predicted[2] / 2, predicted[1] - predicted[3] / 2, predicted[0] + predicted[2] / 2, predicted[1] + predicted[3] / 2
    intersection = max(0.0, min(tx2, px2) - max(tx1, px1)) * max(0.0, min(ty2, py2) - max(ty1, py1))
    union = max(0.0, tx2 - tx1) * max(0.0, ty2 - ty1) + max(0.0, px2 - px1) * max(0.0, py2 - py1) - intersection
    return float(intersection / max(union, 1e-9))


def decode(raw: Any) -> tuple[float, np.ndarray]:
    array = raw.numpy()[0]
    probabilities = 1.0 / (1.0 + np.exp(-array[0]))
    y, x = np.unravel_index(int(probabilities.argmax()), probabilities.shape)
    local = 1.0 / (1.0 + np.exp(-array[1:5, y, x]))
    return float(probabilities[y, x]), np.asarray([(x + local[0]) / GRID_W, (y + local[1]) / GRID_H, local[2], local[3]], dtype=np.float32)


def evaluate(model: BottleGridNet, Tensor: Any, Context: Any, dataset: Path, rows: list[dict[str, Any]], threshold: float, split: str | None = None) -> dict[str, Any]:
    split = split or ("val" if any(row["split"] == "val" for row in rows) else "heldout")
    candidates = [index for index, row in enumerate(rows) if row["split"] == split]
    if not candidates: raise RuntimeError(f"dataset has no {split} rows")
    false_positive = false_negative = correct = 0; iou_sum = 0.0; started = time.perf_counter()
    with Context(TRAINING=0):
        for index in candidates:
            image, present, truth_box, _, _ = samples(dataset, rows, [index])
            confidence, predicted = decode(model(Tensor(image)))
            detected, truth = confidence >= threshold, bool(present[0])
            if truth and detected:
                iou = iou_cxcywh(truth_box[0], predicted); iou_sum += iou; correct += int(iou >= 0.5)
            elif truth: false_negative += 1
            elif detected: false_positive += 1
            else: correct += 1
    positives = sum(bool(samples(dataset, rows, [index])[1][0]) for index in candidates)
    negatives = len(candidates) - positives
    return {"split": split, "frames": len(candidates), "positives": positives, "negatives": negatives,
            "correct": correct, "falsePositive": false_positive, "falseNegative": false_negative,
            "negativeFpr": false_positive / max(negatives, 1), "positiveRecall": (positives - false_negative) / max(positives, 1),
            "meanPositiveIoU": iou_sum / max(positives - false_negative, 1), "fps": len(candidates) / max(time.perf_counter() - started, 1e-9)}


def select_validation_threshold(model: BottleGridNet, Tensor: Any, Context: Any, dataset: Path, rows: list[dict[str, Any]], split: str) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
    trials = []
    for threshold in [round(value, 2) for value in np.arange(0.05, 1.0, 0.05)]:
        metrics = evaluate(model, Tensor, Context, dataset, rows, threshold, split)
        trials.append({"threshold": threshold, **metrics})
    zero_fpr = [trial for trial in trials if trial["negativeFpr"] == 0.0]
    pool = zero_fpr if zero_fpr else trials
    # Threshold selection is validation-only. Favor the lowest safe operating
    # threshold after recall and localization to preserve margin at runtime.
    best = max(pool, key=lambda item: (item["positiveRecall"], item["meanPositiveIoU"], -item["threshold"]))
    return float(best["threshold"]), best, trials


def save_report(path: Path | None, report: dict[str, Any]) -> None:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        os.replace(temporary, path)


def atomic_checkpoint(safe_save: Any, state: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    safe_save(state, temporary)
    os.replace(temporary, path)


def train(args: argparse.Namespace) -> int:
    Tensor, nn, Context, state, _ = tinygrad_imports()
    get_parameters, get_state_dict, _, _, safe_save = state
    _, rows = load_manifest(args.dataset); train_rows = [i for i, row in enumerate(rows) if row["split"] == "train"]
    if not train_rows: raise RuntimeError("dataset has no train rows")
    positive_rows = [index for index in train_rows if rows[index].get("kind") == "positive"]
    negative_rows = [index for index in train_rows if rows[index].get("kind") == "true-negative"]
    rng = np.random.default_rng(args.seed); model = BottleGridNet(nn); optimizer = nn.optim.Adam(get_parameters(model), lr=args.learning_rate); history = []
    with Context(TRAINING=1):
        for step in range(args.steps):
            if positive_rows and negative_rows:
                positive_count = args.batch_size // 2
                picked = rng.choice(positive_rows, size=positive_count, replace=True).tolist()
                picked += rng.choice(negative_rows, size=args.batch_size - positive_count, replace=True).tolist()
                rng.shuffle(picked)
            else:
                picked = rng.choice(train_rows, size=args.batch_size, replace=True).tolist()
            image, _, _, object_target, box_target = samples(args.dataset, rows, picked)
            raw = model(Tensor(image)); object_logit, box_prediction = raw[:, 0:1], raw[:, 1:5].sigmoid()
            target = Tensor(object_target); probability = object_logit.sigmoid()
            # Focal BCE controls the many grid-cell negatives without a tuned
            # inference threshold; positive cells receive fixed extra weight.
            pt = target * probability + (1.0 - target) * (1.0 - probability)
            bce = -(target * probability.log() * args.positive_weight + (1.0 - target) * (1.0 - probability).log())
            object_loss = (((1.0 - pt) ** args.focal_gamma) * bce).mean()
            box_loss = (((box_prediction - Tensor(box_target)) ** 2) * target).sum() / max(float(object_target.sum()), 1.0)
            loss = object_loss + args.box_weight * box_loss
            optimizer.zero_grad(); loss.backward(); optimizer.step()
            if step == 0 or (step + 1) % args.report_every == 0:
                history.append({"step": step + 1, "loss": float(loss.numpy()), "objectnessLoss": float(object_loss.numpy()), "boxRegressionLoss": float(box_loss.numpy())})
            if (step + 1) % args.checkpoint_every == 0:
                atomic_checkpoint(safe_save, get_state_dict(model), args.checkpoint)
                save_report(args.report, {"schema": "puppybot.tinygrad-bottle-training-progress.v1", "completedSteps": step + 1, "checkpoint": str(args.checkpoint), "history": history})
    atomic_checkpoint(safe_save, get_state_dict(model), args.checkpoint)
    if args.validation_split is not None:
        frozen_threshold, validation, threshold_trials = select_validation_threshold(model, Tensor, Context, args.dataset, rows, args.validation_split)
        test = evaluate(model, Tensor, Context, args.dataset, rows, frozen_threshold, args.test_split) if args.test_split is not None else None
    else:
        frozen_threshold, validation, threshold_trials = args.threshold, evaluate(model, Tensor, Context, args.dataset, rows, args.threshold), []
        test = None
    result = {"schema": "puppybot.tinygrad-bottle-training.v6", "backend": "native-tinygrad", "architecture": "Conv stride2 3->8->16; 30x40 cell objectness + local cx/cy/w/h",
              "input": [3, INPUT_SIZE[1], INPUT_SIZE[0]], "grid": [GRID_W, GRID_H], "steps": args.steps, "batchSize": args.batch_size,
              "learningRate": args.learning_rate, "positiveWeight": args.positive_weight, "focalGamma": args.focal_gamma, "boxWeight": args.box_weight,
              "threshold": frozen_threshold, "thresholdProvenance": "selected from validation only" if args.validation_split is not None else "fixed caller threshold",
              "validation": validation, "validationThresholdTrials": threshold_trials, "test": test,
              "checkpoint": str(args.checkpoint), "history": history}
    save_report(args.report, result); print(json.dumps(result, indent=2, sort_keys=True)); return 0


def load_model(args: argparse.Namespace) -> tuple[Any, Any, Any, list[dict[str, Any]], BottleGridNet]:
    Tensor, nn, Context, state, _ = tinygrad_imports(); _, _, load_state_dict, safe_load, _ = state
    _, rows = load_manifest(args.dataset); model = BottleGridNet(nn); load_state_dict(model, safe_load(args.checkpoint)); return Tensor, Context, rows, rows, model


def evaluate_checkpoint(args: argparse.Namespace) -> int:
    Tensor, Context, _, rows, model = load_model(args); result = evaluate(model, Tensor, Context, args.dataset, rows, args.threshold); result["threshold"] = args.threshold; save_report(args.report, result); print(json.dumps(result, indent=2, sort_keys=True)); return 0


def benchmark(args: argparse.Namespace) -> int:
    Tensor, Context, _, rows, model = load_model(args); image, _, _, _, _ = samples(args.dataset, rows, [0])
    with Context(TRAINING=0):
        decode(model(Tensor(image))); elapsed = []
        for _ in range(args.runs):
            started = time.perf_counter(); decode(model(Tensor(image))); elapsed.append((time.perf_counter() - started) * 1000.0)
    result = {"runs": args.runs, "meanMs": float(np.mean(elapsed)), "p95Ms": float(np.percentile(elapsed, 95)), "meanHz": 1000.0 / max(float(np.mean(elapsed)), 1e-9)}
    save_report(args.report, result); print(json.dumps(result, indent=2, sort_keys=True)); return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest="command", required=True)
    train_parser = commands.add_parser("train")
    for p in (train_parser,):
        p.add_argument("--dataset", type=Path, required=True); p.add_argument("--checkpoint", type=Path, required=True); p.add_argument("--report", type=Path, required=True)
        p.add_argument("--steps", type=int, default=480); p.add_argument("--batch-size", type=int, default=8); p.add_argument("--learning-rate", type=float, default=0.003)
        p.add_argument("--positive-weight", type=float, default=20.0); p.add_argument("--focal-gamma", type=float, default=2.0); p.add_argument("--box-weight", type=float, default=6.0)
        p.add_argument("--threshold", type=float, default=0.5); p.add_argument("--report-every", type=int, default=60); p.add_argument("--seed", type=int, default=20260718)
        p.add_argument("--checkpoint-every", type=int, default=25)
        p.add_argument("--validation-split", choices=("validation", "val", "heldout")); p.add_argument("--test-split", choices=("test",))
    for name in ("evaluate", "benchmark"):
        p = commands.add_parser(name); p.add_argument("--dataset", type=Path, required=True); p.add_argument("--checkpoint", type=Path, required=True); p.add_argument("--report", type=Path)
        if name == "evaluate": p.add_argument("--threshold", type=float, required=True)
        else: p.add_argument("--runs", type=int, default=50)
    args = parser.parse_args()
    if args.command == "train": return train(args)
    if args.command == "evaluate": return evaluate_checkpoint(args)
    return benchmark(args)


if __name__ == "__main__": raise SystemExit(main())

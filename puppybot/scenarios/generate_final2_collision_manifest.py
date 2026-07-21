#!/usr/bin/env python3
"""Generate the reviewable PGE collider evidence for PuppyBot final2's URDF visuals.

The script intentionally does not approve or install generated colliders in a
RobotDreams scene. It records all visual geometry, its URDF placement, and PGE's
per-asset result so a reviewer can select and validate any runtime profile.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as element_tree
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FINAL2_ROOT = PROJECT_ROOT / "models" / "puppybot" / "final2"
URDF_PATH = FINAL2_ROOT / "urdf" / "final2.urdf"
DEFAULT_OUTPUT = PROJECT_ROOT / "robotdreams" / "collision" / "final2-link-collider-manifest.v1.json"
STRICT_LINK_PROFILE = PROJECT_ROOT / "robotdreams" / "collision" / "final2-link-collision-profile.v1.json"
ARTIFACT_DIRECTORY = PROJECT_ROOT / "robotdreams" / "collision" / "final2-link-artifacts.v1"
PGE_REPORT_PACKAGE = PROJECT_ROOT / "puppybot" / "collision-tools" / "Cargo.toml"
PGE_REPORT_BINARY = PROJECT_ROOT / "puppybot" / "target" / "debug" / "puppybot-pge-link-collider-report"
FORMAT = "puppybot.final2-link-collider-manifest.v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urdf", type=Path, default=URDF_PATH, help="canonical final2 URDF")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="versioned manifest output")
    parser.add_argument(
        "--skip-pge",
        action="store_true",
        help="write only inventory/blocker evidence; do not invoke the PGE wrapper",
    )
    parser.add_argument("--pge-cache-dir", type=Path, help="resumable per-link PGE report cache")
    parser.add_argument("--max-new-links", type=int, help="generate at most this many uncached links")
    return parser.parse_args()


def float_vector(value: str | None, default: list[float], field: str) -> list[float]:
    if value is None:
        return default
    values = value.split()
    if len(values) != 3:
        raise ValueError(f"{field} must contain exactly three numbers")
    try:
        return [float(item) for item in values]
    except ValueError as error:
        raise ValueError(f"{field} must contain only numbers") from error


def project_relative(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT).as_posix()


def resolve_package_uri(uri: str) -> Path | None:
    prefix = "package://final2/"
    if not uri.startswith(prefix):
        return None
    return FINAL2_ROOT / uri.removeprefix(prefix)


def visual_entry(link_name: str, visual_index: int, visual: element_tree.Element) -> dict[str, Any]:
    mesh = visual.find("geometry/mesh")
    if mesh is None or "filename" not in mesh.attrib:
        return {
            "visualIndex": visual_index,
            "status": "blocked",
            "blocker": "visual geometry is not a mesh with a filename",
        }
    origin = visual.find("origin")
    uri = mesh.attrib["filename"]
    path = resolve_package_uri(uri)
    extension = Path(uri).suffix.lower().removeprefix(".")
    source: dict[str, Any] = {
        "urdfUri": uri,
        "format": extension or None,
        "pgeLoaderCompatible": extension in ("gltf", "glb"),
    }
    if path is None:
        source["projectPath"] = None
        source["exists"] = False
        blocker = "URI is not in the canonical package://final2/ namespace"
    else:
        source["projectPath"] = project_relative(path)
        source["exists"] = path.is_file()
        blocker = None if path.is_file() else "referenced mesh asset is missing"
    if blocker is None and not source["pgeLoaderCompatible"]:
        blocker = "PGE collision loader accepts only .gltf and .glb assets"
    entry: dict[str, Any] = {
        "visualIndex": visual_index,
        "source": source,
        "assetToLink": {
            "translation_m": float_vector(origin.attrib.get("xyz") if origin is not None else None, [0.0, 0.0, 0.0], "visual origin xyz"),
            "rotation_rpy_rad": float_vector(origin.attrib.get("rpy") if origin is not None else None, [0.0, 0.0, 0.0], "visual origin rpy"),
            "scale": float_vector(mesh.attrib.get("scale"), [1.0, 1.0, 1.0], "mesh scale"),
        },
    }
    if blocker is not None:
        entry.update({"status": "blocked", "blocker": blocker})
    else:
        entry["status"] = "pending_pge"
    return entry


def inventory(urdf_path: Path) -> list[dict[str, Any]]:
    root = element_tree.parse(urdf_path).getroot()
    links = []
    for link in root.findall("link"):
        link_name = link.attrib.get("name")
        if not link_name:
            raise ValueError("URDF contains a link without a name")
        links.append(
            {
                "linkName": link_name,
                "visuals": [visual_entry(link_name, index, visual) for index, visual in enumerate(link.findall("visual"))],
            }
        )
    return links


def pge_requests(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requests = []
    for link in links:
        for visual in link["visuals"]:
            if visual["status"] != "pending_pge":
                continue
            requests.append(
                {
                    "link_name": link["linkName"],
                    "asset_id": f"visual-{visual['visualIndex']}",
                    "asset_path": visual["source"]["projectPath"],
                    "asset_to_link": visual["assetToLink"],
                }
            )
    return requests


def run_pge(
    requests: list[dict[str, Any]], cache_dir: Path | None = None, max_new_links: int | None = None
) -> dict[str, Any]:
    combined: dict[str, Any] | None = None
    results = []
    link_results = []
    generated_new_links = 0
    missing_links = []
    if max_new_links is not None and (max_new_links < 1 or cache_dir is None):
        raise ValueError("--max-new-links must be positive and requires --pge-cache-dir")
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
    start = 0
    build = subprocess.run(
        ["cargo", "build", "--quiet", "--manifest-path", str(PGE_REPORT_PACKAGE)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if build.returncode:
        details = build.stderr.strip() or build.stdout.strip()
        raise RuntimeError(f"could not build PGE collider wrapper: {details}")
    if not PGE_REPORT_BINARY.is_file():
        raise RuntimeError(f"PGE collider wrapper was not built at {PGE_REPORT_BINARY}")
    with tempfile.TemporaryDirectory(prefix="puppybot-final2-collision-") as temporary:
        temporary_path = Path(temporary)
        # One PGE invocation per URDF link bounds peak memory for the complete
        # CAD assembly. Adjacent visuals of a link remain together so PGE can
        # construct one complete physical-link candidate from every source.
        while start < len(requests):
            link_name = requests[start]["link_name"]
            end = start + 1
            while end < len(requests) and requests[end]["link_name"] == link_name:
                end += 1
            batch = requests[start:end]
            cache_path = cache_dir / f"{start:04d}-{link_name}.json" if cache_dir is not None else None
            if cache_path is not None and cache_path.is_file():
                report = json.loads(cache_path.read_text(encoding="utf-8"))
                results.extend(report["results"])
                link_results.extend(report["linkResults"])
                if combined is None:
                    combined = {key: value for key, value in report.items() if key not in ("results", "linkResults")}
                start = end
                continue
            if max_new_links is not None and generated_new_links >= max_new_links:
                missing_links.append(link_name)
                start = end
                continue
            input_path = temporary_path / f"requests-{start}.json"
            output_path = temporary_path / f"report-{start}.json"
            input_path.write_text(json.dumps(batch), encoding="utf-8")
            command = [str(PGE_REPORT_BINARY), str(input_path), str(output_path)]
            completed = subprocess.run(command, cwd=PROJECT_ROOT, text=True, capture_output=True, check=False)
            if completed.returncode:
                details = completed.stderr.strip() or completed.stdout.strip()
                results.extend(
                    {
                        "status": "failed",
                        "link_name": request["link_name"],
                        "asset_id": request["asset_id"],
                        "asset_path": request["asset_path"],
                        "reason": f"PGE wrapper process failed (exit {completed.returncode}): {details or 'no diagnostic output'}",
                    }
                    for request in batch
                )
                results_link = {
                    "status": "failed",
                    "link_name": link_name,
                    "asset_count": len(batch),
                    "generated_asset_count": 0,
                    "reason": f"PGE wrapper process failed (exit {completed.returncode}): {details or 'no diagnostic output'}",
                }
                link_results.append(results_link)
            else:
                report = json.loads(output_path.read_text(encoding="utf-8"))
                if len(report.get("results", [])) != len(batch):
                    raise ValueError("PGE wrapper did not return every result in a link batch")
                if len(report.get("linkResults", [])) != 1:
                    raise ValueError("PGE wrapper did not return exactly one aggregate result for a link batch")
                if combined is None:
                    combined = {key: value for key, value in report.items() if key != "results"}
                results.extend(report["results"])
                link_results.extend(report["linkResults"])
                if cache_path is not None:
                    cache_path.write_text(json.dumps(report), encoding="utf-8")
            generated_new_links += 1
            start = end
    if missing_links:
        raise RuntimeError(f"PGE cache is incomplete; remaining links: {','.join(missing_links)}")
    if combined is None:
        # Every attempt was a process-level failure. Keep generation settings
        # visible while retaining explicit failure records for all assets.
        combined = {
            "format": "puppybot.pge-link-collider-report.v1",
            "generator": "puppybot-pge-link-collider-report",
            "pgeCollisionVersion": "0.1.0",
            "generationConfig": {"max_compound_parts": 4, "minimum_extent": 0.001},
            "maximumReviewedColliders": 4,
        }
    combined["results"] = results
    combined["linkResults"] = link_results
    return combined


def attach_pge_results(links: list[dict[str, Any]], report: dict[str, Any]) -> None:
    pending = [visual for link in links for visual in link["visuals"] if visual["status"] == "pending_pge"]
    results = report.get("results")
    if not isinstance(results, list) or len(results) != len(pending):
        raise ValueError("PGE report does not contain one ordered result for every eligible visual")
    for visual, result in zip(pending, results, strict=True):
        status = result.get("status")
        if status == "generated":
            visual["status"] = "generated_candidate"
            visual["pge"] = {
                "provenance": result["provenance"],
                "assetId": result["assetId"],
            }
        elif status == "failed":
            visual["status"] = "blocked"
            visual["blocker"] = result["reason"]
            visual["pge"] = {"assetPath": result["asset_path"]}
        else:
            raise ValueError(f"PGE report contains unsupported result status: {status!r}")
    link_results = report.get("linkResults")
    links_with_visuals = [link for link in links if link["visuals"]]
    if not isinstance(link_results, list) or len(link_results) != len(links_with_visuals):
        raise ValueError("PGE report does not contain one ordered aggregate result for every link with visuals")
    for link, result in zip(links_with_visuals, link_results, strict=True):
        status = result.get("status")
        if status == "generated":
            link["pge"] = {
                "status": "generated_candidate",
                "sourceAssets": result["sourceAssets"],
                "reviewedProfile": result["reviewedProfile"],
                "selectionEvidence": result["selectionEvidence"],
            }
            link["reviewStatus"] = "candidate only; human review and scene-specific validation required"
        elif status == "failed":
            link["pge"] = {
                "status": "blocked",
                "assetCount": result["asset_count"],
                "generatedAssetCount": result["generated_asset_count"],
                "blocker": result["reason"],
            }
        else:
            raise ValueError(f"PGE report contains unsupported link result status: {status!r}")


def manifest(urdf_path: Path, links: list[dict[str, Any]], report: dict[str, Any] | None) -> dict[str, Any]:
    visuals = [visual for link in links for visual in link["visuals"]]
    statuses = Counter(visual["status"] for visual in visuals)
    formats = Counter(visual.get("source", {}).get("format") for visual in visuals)
    source_paths = {
        visual["source"]["projectPath"]
        for visual in visuals
        if visual.get("source", {}).get("projectPath")
    }
    return manifest_document(urdf_path, links, report, visuals, statuses, formats, source_paths)


def write_strict_artifacts(report: dict[str, Any]) -> None:
    """Write PGE candidates and reviewed profiles as separate RobotDreams inputs."""
    candidates_dir = ARTIFACT_DIRECTORY / "candidates"
    reviewed_dir = ARTIFACT_DIRECTORY / "reviewed"
    evidence_dir = ARTIFACT_DIRECTORY / "evidence"
    for directory in (candidates_dir, reviewed_dir, evidence_dir):
        directory.mkdir(parents=True, exist_ok=True)
    entries = []
    generated = [result for result in report["linkResults"] if result["status"] == "generated"]
    failed = [result for result in report["linkResults"] if result["status"] != "generated"]
    if failed:
        raise RuntimeError(f"refusing strict profile: {len(failed)} physical links did not generate")
    for index, result in enumerate(generated):
        stem = f"{index:03d}"
        candidate_path = candidates_dir / f"{stem}.json"
        reviewed_path = reviewed_dir / f"{stem}.json"
        evidence_path = evidence_dir / f"{stem}.json"
        candidate_path.write_text(json.dumps(result["candidates"], indent=2) + "\n", encoding="utf-8")
        reviewed_path.write_text(json.dumps(result["reviewedProfile"], indent=2) + "\n", encoding="utf-8")
        evidence_path.write_text(
            json.dumps(
                {"link": result["linkName"], "sourceAssets": result["sourceAssets"], "selectionEvidence": result["selectionEvidence"]},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        entries.append(
            {
                "link": result["linkName"],
                "candidateArtifact": f"final2-link-artifacts.v1/candidates/{stem}.json",
                "reviewedProfile": f"final2-link-artifacts.v1/reviewed/{stem}.json",
            }
        )
    STRICT_LINK_PROFILE.write_text(
        json.dumps({"format": "robotdreams.link-collision-profile.v1", "robot": "puppybot", "links": entries}, indent=2)
        + "\n",
        encoding="utf-8",
    )
def manifest_document(urdf_path: Path, links: list[dict[str, Any]], report: dict[str, Any] | None, visuals: list[dict[str, Any]], statuses: Counter[str], formats: Counter[str | None], source_paths: set[str]) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "status": "candidate_evidence_only",
        "source": {
            "urdf": project_relative(urdf_path),
            "sha256": hashlib.sha256(urdf_path.read_bytes()).hexdigest(),
            "packageResolution": {"package://final2/": "models/puppybot/final2/"},
        },
        "pgeLoader": {
            "acceptedFormats": ["gltf", "glb"],
            "geometryRequirements": "default scene; triangle-list primitives with POSITION data",
            "transformPolicy": "PGE applies glTF node transforms, then the URDF visual assetToLink transform",
            "multiVisualLinkPolicy": "every visual has a unique asset ID within its link; PGE aggregates all generated assets into one physical-link candidate",
        },
        "generation": (
            {
                "tool": report["generator"],
                "pgeCollisionVersion": report["pgeCollisionVersion"],
                "generationConfig": report["generationConfig"],
                "maximumReviewedColliders": report["maximumReviewedColliders"],
            }
            if report is not None
            else {"status": "not_run", "reason": "--skip-pge"}
        ),
        "summary": {
            "linkCount": len(links),
            "visualCount": len(visuals),
            "linksWithoutVisualGeometry": [link["linkName"] for link in links if not link["visuals"]],
            "uniqueMeshAssetCount": len(source_paths),
            "formats": dict(sorted(formats.items(), key=lambda item: str(item[0]))),
            "statuses": dict(sorted(statuses.items())),
            "linkGenerationStatuses": dict(
                sorted(
                    Counter(link.get("pge", {}).get("status", "no_visual_geometry") for link in links).items()
                )
            ),
        },
        "links": links,
    }


def main() -> int:
    arguments = parse_args()
    try:
        urdf_path = arguments.urdf.resolve()
        links = inventory(urdf_path)
        report = None
        if arguments.skip_pge:
            for link in links:
                for visual in link["visuals"]:
                    if visual["status"] == "pending_pge":
                        visual["status"] = "not_generated"
                        visual["blocker"] = "PGE generation deliberately skipped"
        else:
            report = run_pge(pge_requests(links), arguments.pge_cache_dir, arguments.max_new_links)
            attach_pge_results(links, report)
            write_strict_artifacts(report)
        output = arguments.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest(urdf_path, links, report), indent=2) + "\n", encoding="utf-8")
    except (OSError, RuntimeError, ValueError, element_tree.ParseError) as error:
        print(f"generate_final2_collision_manifest: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

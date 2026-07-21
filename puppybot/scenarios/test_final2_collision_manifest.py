#!/usr/bin/env python3
"""Regression checks for the canonical final2 visual-collider inventory."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCENARIOS = Path(__file__).parent
GENERATOR = SCENARIOS / "generate_final2_collision_manifest.py"
SPEC = importlib.util.spec_from_file_location("generate_final2_collision_manifest", GENERATOR)
assert SPEC is not None and SPEC.loader is not None
manifest_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manifest_tool)


class Final2CollisionManifestTests(unittest.TestCase):
    def test_inventory_has_every_canonical_link_and_visual(self) -> None:
        links = manifest_tool.inventory(manifest_tool.URDF_PATH)
        document = manifest_tool.manifest(manifest_tool.URDF_PATH, links, None)

        self.assertEqual(document["format"], manifest_tool.FORMAT)
        self.assertEqual(document["summary"]["linkCount"], 221)
        self.assertEqual(document["summary"]["visualCount"], 221)
        self.assertEqual(document["summary"]["uniqueMeshAssetCount"], 188)
        self.assertEqual(document["summary"]["formats"], {"gltf": 221})
        self.assertEqual(document["summary"]["linksWithoutVisualGeometry"], ["turning_rod__1__loop_closure"])
        self.assertTrue(
            all(
                visual["source"]["exists"] and visual["source"]["pgeLoaderCompatible"]
                for link in links
                for visual in link["visuals"]
            )
        )

    def test_root_preserves_both_visual_assets_and_transforms(self) -> None:
        links = manifest_tool.inventory(manifest_tool.URDF_PATH)
        root = next(link for link in links if link["linkName"] == "root")

        self.assertEqual(len(root["visuals"]), 2)
        self.assertNotEqual(root["visuals"][0]["source"]["projectPath"], root["visuals"][1]["source"]["projectPath"])
        for visual in root["visuals"]:
            self.assertEqual(len(visual["assetToLink"]["translation_m"]), 3)
            self.assertEqual(len(visual["assetToLink"]["rotation_rpy_rad"]), 3)
            self.assertEqual(len(visual["assetToLink"]["scale"]), 3)

    def test_skip_generation_keeps_all_sources_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "manifest.json"
            original_argv = manifest_tool.sys.argv
            try:
                manifest_tool.sys.argv = ["generate_final2_collision_manifest.py", "--skip-pge", "--output", str(output)]
                self.assertEqual(manifest_tool.main(), 0)
            finally:
                manifest_tool.sys.argv = original_argv
            document = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(document["generation"]["status"], "not_run")
        self.assertEqual(document["summary"]["statuses"], {"not_generated": 221})


if __name__ == "__main__":
    unittest.main()

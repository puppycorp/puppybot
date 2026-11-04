#!/usr/bin/env python3
"""CPU-only v3/v4 scene-label binding regression checks."""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('metadata',ROOT/'flex/tests/verify-sim-visual-validation-v4-metadata.py')
metadata=importlib.util.module_from_spec(spec);spec.loader.exec_module(metadata)
BASE=ROOT/'build/flex/sim/levels-v2/pitch82';V3=BASE/'visual-stop-validation-inputs-v3';V4=BASE/'visual-stop-validation-inputs-v4';RESET=BASE/'visual-stop-validation-inputs-v4-reset-report.json'


class MetadataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not all(p.is_file() for p in (V3/'conditions.json',V4/'conditions.json',RESET)):raise AssertionError('required frozen v3/v4/reset fixtures are unavailable')
        cls.old=json.loads((V3/'conditions.json').read_text())['conditions'];cls.new=json.loads((V4/'conditions.json').read_text())['conditions']

    def test_real_frozen_metadata_and_reset_match(self):
        self.assertEqual(metadata.audit(V3,V4,RESET)['conditions'],12)

    def test_family_heading_type_and_controller_tampering_rejected(self):
        for mutate in (lambda rows:rows[0].__setitem__('family','periodic'),
                       lambda rows:rows[0].__setitem__('spawnHeading',.9),
                       lambda rows:rows[0].__setitem__('classification',True),
                       lambda rows:rows[-1].__setitem__('layout',True),
                       lambda rows:rows[-1].__setitem__('caseControllerChange','none')):
            rows=copy.deepcopy(self.new);mutate(rows)
            with self.assertRaises(ValueError):metadata.compare_rows(self.old,rows)

    def test_reset_report_wrong_pilot_rejected(self):
        result=json.loads(RESET.read_text());result['pilot']='/tmp/not-the-recorded-pilot'
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'report.json';path.write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError,'identity differs'):metadata.audit(V3,V4,path)

    def test_added_removed_or_duplicate_labels_rejected(self):
        rows=copy.deepcopy(self.new);rows[0]['unrecorded']='x'
        with self.assertRaises(ValueError):metadata.compare_rows(self.old,rows)
        rows=copy.deepcopy(self.new);rows[1]['name']=rows[0]['name']
        with self.assertRaises(ValueError):metadata.compare_rows(self.old,rows)
        rows=copy.deepcopy(self.new);rows[0]['cpuParserPreflight']['accepted']=False
        with self.assertRaises(ValueError):metadata.compare_rows(self.old,rows)


if __name__=='__main__':unittest.main()

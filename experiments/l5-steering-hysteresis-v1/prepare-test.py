#!/usr/bin/env python3
"""Disposable source-consistency fixtures; no build or GPU."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('hys_prepare_test',HERE/'prepare.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class BuildTest(unittest.TestCase):
    def test_rejects_coherently_altered_unrelated_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original=root/'flex/control';original.mkdir(parents=True);(original/'chase.flex').write_text('old chase');(original/'main.flex').write_text('old main');(original/'other.flex').write_text('untouched')
            here=root/'experiment';here.mkdir();(here/'native-test-probe.flex').write_text('probe')
            build=root/'build';control=build/'flex-source/control';control.mkdir(parents=True);(control/'chase.flex').write_text('new chase');(control/'main.flex').write_text('new main');(control/'other.flex').write_text('untouched');(control/'hysteresis-test-probe.flex').write_text('probe')
            (build/'original-chase.flex').write_text('old chase');(build/'original-main.flex').write_text('old main');(build/'control').write_bytes(b'control');(build/'probe').write_bytes(b'probe')
            source=m.base.hidden.supervisor.source_hashes
            report={'schema':'puppybot.l5-steering-hysteresis-build.v1','status':'diagnostic_build_only','inputs':{},'originalSources':source(root/'flex'),'patchedSources':source(build/'flex-source'),'controlSHA256':m.base.sha(build/'control'),'probeSHA256':m.base.sha(build/'probe')}
            (build/'build.json').write_text(json.dumps(report))
            transform=type('Transform',(),{'transform':staticmethod(lambda chase,main:('new chase','new main'))})
            with mock.patch.object(m,'ROOT',root),mock.patch.object(m,'HERE',here),mock.patch.object(m,'BUILD',build),mock.patch.object(m,'input_paths',return_value=()),mock.patch.object(m,'transform',transform):
                self.assertEqual(m.verify(build),report)
                (control/'other.flex').write_text('altered');report['patchedSources']=source(build/'flex-source');(build/'build.json').write_text(json.dumps(report))
                with self.assertRaisesRegex(ValueError,'unrelated candidate source'):m.verify(build)


if __name__=='__main__':unittest.main()

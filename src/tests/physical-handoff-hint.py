#!/usr/bin/env python3
"""CPU-only isolated build and sighting-memory regression tests."""
import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('prepare',ROOT/'flex/tests/prepare-physical-handoff-hint.py')
prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)


class HintTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name);cls.build=cls.root/'build'
        cls.report=prepare.prepare(cls.build);source=cls.build/'inputs/flex-source/sim';text=(source/'main.flex').read_text()
        if text.count('fn main(argc, argv) {')!=1:raise ValueError('candidate main shape changed')
        text=text.replace('fn main(argc, argv) {','fn ph_hint_original_main(argc, argv) {',1)
        text=re.sub(r'^import "([^"/]+\.flex)";',lambda m:f'import "{source/m.group(1)}";',text,flags=re.M)
        text+='\n'+(ROOT/'flex/tests/physical-handoff-hint-native.flex').read_text()
        probe=cls.root/'probe.flex';probe.write_text(text);cls.binary=cls.root/'probe'
        subprocess.run([str(prepare.rescan.COMPILER),str(probe),'-o',str(cls.binary)],cwd=ROOT,check=True,timeout=60,capture_output=True)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_real_compiled_hint_and_confirmation_gates(self):
        result=subprocess.run([str(self.binary)],cwd=ROOT,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
        self.assertIn('Physical RGB handoff hint CPU probe passed',result.stdout)

    def test_actual_handoff_order_with_cpu_sensor_mocks(self):
        # Isolate a second copy for mocked sensor/actuator functions; the
        # candidate simulator and its frozen source remain untouched.
        shadow=self.root/'protocol';shutil.copytree(self.build/'inputs/flex-source',shadow/'flex-source');shutil.copytree(self.build/'inputs/build',shadow/'build')
        source=shadow/'flex-source';library=shadow/'build/flex/sim/library'
        adapter=library/'lib/f64.flex';old=str(self.build/'inputs/flex-source/core/words.flex');new=str(source/'core/words.flex')
        text=adapter.read_text();self.assertEqual(text.count(old),1);adapter.write_text(text.replace(old,new,1))
        (shadow/'build/flex/sim/dependencies.flex').write_text(f'import "{library/"libs/render.flex"}";\nimport "{library/"libs/physics/physics.flex"}";\n')
        def replace_function(path,start,next_name,replacement):
            text=path.read_text();a=text.index('fn '+start+'(');b=text.index('fn '+next_name+'(',a);path.write_text(text[:a]+replacement+'\n'+text[b:])
        brick=source/'sim/brick-vision.flex'
        replace_function(brick,'ps_brick_detect','ps_rgb_sample','fn ps_brick_detect() { return ph_mock_detect; }')
        replace_function(brick,'ps_rgb_sample','ps_brick_sample','fn ps_rgb_sample() { if !ph_mock_rgb { return 0; } if !ph_mock_stale { ps_brick_frame=ps_total; } return 1; }')
        dock=source/'sim/dock-vision.flex'
        replace_function(dock,'ps_dock_detect','ps_dock_mark','fn ps_dock_detect() { return 0; }')
        replace_function(dock,'ps_dock_attention','ps_dock_sample','fn ps_dock_attention(found) { return found; }')
        floor=source/'sim/floor-memory.flex';replace_function(floor,'ps_floor_observe','ps_floor_forget','fn ps_floor_observe() { return 0; }')
        collect=source/'sim/collect.flex';replace_function(collect,'ps_collect_search_begin','ps_collect_attention','fn ps_collect_search_begin() { return ph_mock_collector; }')
        agent=source/'sim/agent.flex';replace_function(agent,'ps_physical_stop_before_handoff','ps_physical_abort','fn ps_physical_stop_before_handoff() { return ph_mock_stop; }')
        replace_function(agent,'ps_physical_halt','ps_physical_io','fn ps_physical_halt() { ps_physical_owner=2; ps_physical_ack=6; return 0; }')
        main=source/'sim/main.flex';text=main.read_text();self.assertEqual(text.count('fn main(argc, argv) {'),1)
        text=text.replace('global ps_robot = 0;','global ph_mock_stop=1; global ph_mock_rgb=1; global ph_mock_detect=1; global ph_mock_stale=0; global ph_mock_collector=1;\nglobal ps_robot = 0;',1)
        main.write_text(text.replace('fn main(argc, argv) {','fn ph_protocol_original_main(argc, argv) {',1)+'\n'+(ROOT/'flex/tests/physical-handoff-hint-protocol.flex').read_text())
        binary=self.root/'protocol-probe';built=subprocess.run([str(prepare.rescan.COMPILER),str(main),'-o',str(binary)],cwd=ROOT,timeout=60,capture_output=True,text=True);self.assertEqual(built.returncode,0,built.stdout+'\n'+built.stderr)
        result=subprocess.run([str(binary)],cwd=ROOT,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr);self.assertIn('handoff ordering CPU probe passed',result.stdout)

    def test_isolated_opt_in_only_and_trace_only_diagnostics(self):
        source=self.build/'inputs/flex-source/sim';main=(source/'main.flex').read_text();agent=(source/'agent.flex').read_text();collect=(source/'collect.flex').read_text()
        self.assertIn('PUPPYBOT_PHYSICAL_HANDOFF_HINT',main)
        self.assertIn('if ps_agent_physical && ps_handoff_hint_enabled && ps_output >= 0',main)
        self.assertIn('if !ps_collect_search_begin() { return ps_physical_halt(); }\n    ps_handoff_hint_capture();',agent)
        self.assertNotIn('handoffHint',agent[agent.index('fn ps_physical_observe()'):agent.index('fn ps_physical_stop_before_handoff()')])
        self.assertIn('ps_total - load64(ps_handoff_hint + 32) > 500',collect)
        self.assertEqual(self.report['hintMaxAgeTicks'],500)
        self.assertNotEqual(self.report['baselineSimulatorSHA256'],self.report['candidateSimulatorSHA256'])
        self.assertTrue(prepare.verify(self.build,self.report))

    def test_transform_refuses_changed_source_and_existing_destination(self):
        for name,fn in (('collect.flex',prepare.transform_collect),('agent.flex',prepare.transform_agent),('main.flex',prepare.transform_main)):
            source=(self.build/'original-source'/name).read_text();transformed=fn(source)
            with self.assertRaises(ValueError):fn(transformed)
        with self.assertRaises(FileExistsError):prepare.prepare(self.build)

    def test_dependency_imports_are_bound(self):
        path=self.build/'inputs/build/flex/sim/dependencies.flex';original=path.read_text()
        try:
            path.write_text(original+'\n')
            with self.assertRaises(ValueError):prepare.verify(self.build,self.report)
        finally:path.write_text(original)


if __name__=='__main__':unittest.main()

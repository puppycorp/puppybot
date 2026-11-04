#!/usr/bin/env python3
"""CPU checks of copied waypoint state and saved-map planner behavior."""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARCHIVE = ROOT / 'build/flex/sim/levels-v2/pitch82/dock-floor-refresh-build-v2'
COMPILER = ROOT / 'build/flex/control/compiler'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


transform = load('short_waypoint_transform', HERE / 'transform.py')
builder = load('saved_floor_refresh_build', ROOT / 'experiments/dock-floor-refresh-v1/build.py')
previous = load('saved_floor_refresh_test', ROOT / 'experiments/dock-floor-refresh-v1/test.py')


class WaypointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        builder.verify(ARCHIVE)
        cls.temp = tempfile.TemporaryDirectory(prefix='puppy-dock-short-waypoint-')
        root = Path(cls.temp.name); source = root / 'source'; build = root / 'build'
        shutil.copytree(ARCHIVE / 'source', source); shutil.copytree(ARCHIVE / 'build', build)
        library = build / 'flex/sim/library'; adapter = library / 'lib/f64.flex'
        adapter.write_text(transform.once(adapter.read_text(),
            f'import "{ARCHIVE / "source/core/words.flex"}";', f'import "{source / "core/words.flex"}";'))
        (library.parent / 'dependencies.flex').write_text(f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
        sim = source / 'sim'; dock = sim / 'dock-search.flex'; main = sim / 'main.flex'
        dock_text, main_text = transform.transform(dock.read_text(), main.read_text())
        dock.write_text(dock_text); main.write_text(main_text)
        cls.binary = root / 'simulator'
        subprocess.run([str(COMPILER),str(main),'-o',str(cls.binary)],cwd=ROOT,capture_output=True,text=True,timeout=120,check=True)
        replacements = {
            'dock-search.flex': {'ps_dock_search_stage': 'fn ps_dock_search_stage() { probe_stage_calls = probe_stage_calls + 1; return 0; }'},
            'dock-vision.flex': {'ps_dock_fresh': 'fn ps_dock_fresh() { return probe_fresh; }'},
            'navigation.flex': {
                'ps_nav_plan': '''fn ps_nav_plan(x, y, heading) { probe_plan_calls = probe_plan_calls + 1;
                    if probe_deadline_fault { ps_nav_deadline_fault = 1; return 0; }
                    ps_nav_path_count = probe_path_count; return probe_route; }''',
                'ps_nav_clear': 'fn ps_nav_clear(x, y, heading) { return 1; }',
                'ps_nav_end_pose': 'fn ps_nav_end_pose(out) { store64(out, probe_endpoint_x); store64(out + 8, 0); store64(out + 16, 0); return 1; }'},
            'collect.flex': {'ps_collect_map_begin': 'fn ps_collect_map_begin() { return 0; }'},
            'case.flex': {'ps_case_fail': 'fn ps_case_fail(reason) { probe_fails = probe_fails + 1; ps_case_stage = 13; return 0; }',
                          'ps_case_travel_pose': 'fn ps_case_travel_pose() { return probe_travel_ok; }'},
        }
        for name, functions in replacements.items():
            path=sim/name;text=path.read_text()
            for fn,body in functions.items(): text=previous.replace_function(text,fn,body)
            if name=='dock-search.flex':
                text=transform.once(text,'    pb_drive_stop(pb_robot_drive(ps_robot), ps_time);\n    ps_dock_search_staged = 0;',
                    '    ps_dock_search_staged = 0;')
            path.write_text(text)
        text=main.read_text(); probe=(HERE/'probe.flex').read_text(); globals_, funcs=probe.split('fn probe_reset()',1)
        text=transform.once(text,'global ps_robot = 0;',globals_+'\nglobal ps_robot = 0;')
        main.write_text(transform.once(text,'fn main(argc, argv) {','fn waypoint_old_main(argc, argv) {')+'\nfn probe_reset()'+funcs)
        cls.probe=root/'probe'
        subprocess.run([str(COMPILER),str(main),'-o',str(cls.probe)],cwd=ROOT,capture_output=True,text=True,timeout=120,check=True)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_copied_simulator_rejects_invalid_opt_in(self):
        result=subprocess.run([str(self.binary),'--help'],cwd=ROOT,env=dict(os.environ,PUPPYBOT_SIM_DOCK_SHORT_WAYPOINT='invalid'),capture_output=True,text=True,timeout=30)
        self.assertNotEqual(result.returncode,0);self.assertIn('Invalid dock short waypoint option',result.stderr)

    def test_waypoint_state_machine_and_fail_closed_guards(self):
        result=subprocess.run([str(self.probe)],cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertIn('state checks passed',result.stdout)

    def test_saved_map_native_planner_with_reconstructed_contacts(self):
        result=subprocess.run(['python3','-B','-I',str(ROOT/'experiments/dock-waypoint-diagnostic-v1/audit.py')],cwd=ROOT,capture_output=True,text=True,timeout=60,check=True)
        report=json.loads(result.stdout); candidate=report['rows'][-1]
        self.assertEqual(report['mapFrameId'],21179);self.assertEqual(len(report['reconstructedContacts']),2)
        self.assertEqual((candidate['result'],candidate['attemptedPlans'],candidate['pathCount']),(1,1,4))


if __name__ == '__main__': unittest.main()

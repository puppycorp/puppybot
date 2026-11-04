#!/usr/bin/env python3
"""CPU-only real dispatch on a disposable source copy with sensor mocks."""
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('search_build',HERE/'prepare.py')
prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)


def replace_function(path,start,next_name,replacement):
    text=path.read_text();a=text.index('fn '+start+'(');b=text.index('fn '+next_name+'(',a)
    path.write_text(text[:a]+replacement+'\n'+text[b:])


class SearchDispatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='puppy-search-dispatch-');cls.root=Path(cls.temp.name)
        cls.build=cls.root/'candidate';cls.report=prepare.build(cls.build)
        cls.shadow=cls.root/'shadow';shutil.copytree(cls.build/'source',cls.shadow/'source');shutil.copytree(cls.build/'build',cls.shadow/'build')
        source=cls.shadow/'source';library=cls.shadow/'build/flex/sim/library'
        adapter=library/'lib/f64.flex';text=adapter.read_text();old=str(cls.build/'source/core/words.flex');new=str(source/'core/words.flex')
        if text.count(old)!=1:raise ValueError('shadow dependency shape changed')
        adapter.write_text(text.replace(old,new,1))
        (library.parent/'dependencies.flex').write_text(f'import "{library/"libs/render.flex"}";\nimport "{library/"libs/physics/physics.flex"}";\n')
        brick=source/'sim/brick-vision.flex'
        replace_function(brick,'ps_brick_detect','ps_rgb_sample','fn ps_brick_detect() { return sf_mock_detect; }')
        replace_function(brick,'ps_rgb_sample','ps_brick_sample','fn ps_rgb_sample() { sf_mock_samples=sf_mock_samples+1; if !sf_mock_rgb || sf_mock_stops!=1 { return 0; } if !sf_mock_stale { ps_brick_frame=ps_total; } return 1; }')
        camera=source/'sim/camera.flex';replace_function(camera,'ps_camera_still','ps_camera_observation','fn ps_camera_still() { return sf_mock_camera; }')
        collect=source/'sim/collect.flex';replace_function(collect,'ps_collect_search_begin','ps_collect_attention','fn ps_collect_search_begin() { sf_mock_count=sf_mock_count+1; if sf_mock_samples!=1 { return 0; } return sf_mock_collector; }')
        agent=source/'sim/agent.flex'
        replace_function(agent,'ps_physical_io','ps_physical_observe','fn ps_physical_io(reading,data,size) { if !reading || size != 64 || sf_loop_requests >= 2 { return 0; } pb_zero(data,64); if !sf_loop_requests { store64(data,8); } else { store64(data,3); } store64(data+8,sf_loop_requests+1); store64(data+48,4); sf_loop_requests=sf_loop_requests+1; return 1; }')
        replace_function(agent,'ps_physical_observe','ps_physical_stop_before_handoff','fn ps_physical_observe() { if !sf_loop_observations { if ps_physical_owner!=1 || ps_physical_ack!=8 { return 0; } } else { if ps_physical_owner!=2 || ps_physical_ack!=7 { return 0; } } sf_loop_observations=sf_loop_observations+1; return 1; }')
        replace_function(agent,'ps_physical_stop_before_handoff','ps_physical_abort','fn ps_physical_stop_before_handoff() { sf_mock_stops=sf_mock_stops+1; return sf_mock_stop; }')
        replace_function(agent,'ps_physical_halt','ps_physical_io','fn ps_physical_halt() { ps_physical_owner=2; ps_physical_ack=6; return 0; }')
        text=agent.read_text();marker='let request = alloc(64); let initialized = 0; let running = 1; ps_agent_sequence = 0;'
        if text.count(marker)!=1:raise ValueError('physical loop shape changed')
        # Seed only the disposable loop probe after reset; command dispatch,
        # ownership and ACK behavior remain the real candidate implementation.
        agent.write_text(text.replace(marker,marker.replace('initialized = 0','initialized = 1'),1))
        main=source/'sim/main.flex';text=main.read_text()
        declarations='global sf_mock_stop=1; global sf_mock_rgb=1; global sf_mock_detect=1; global sf_mock_stale=0; global sf_mock_collector=1; global sf_mock_camera=1; global sf_mock_count=0; global sf_mock_samples=0; global sf_mock_stops=0; global sf_loop_requests=0; global sf_loop_observations=0;\n'
        if text.count('global ps_robot = 0;')!=1 or text.count('fn main(argc, argv) {')!=1:raise ValueError('candidate main shape changed')
        text=text.replace('global ps_robot = 0;',declarations+'global ps_robot = 0;',1).replace('fn main(argc, argv) {','fn sf_original_main(argc, argv) {',1)
        main.write_text(text+'\n'+(HERE/'test_dispatch.flex').read_text())
        cls.binary=cls.root/'dispatch';built=subprocess.run([str(prepare.COMPILER),str(main),'-o',str(cls.binary)],cwd=ROOT,capture_output=True,text=True,timeout=120)
        if built.returncode:raise RuntimeError(built.stdout+'\n'+built.stderr)
        # A separate shadow preserves the actual search-start routine; only
        # physical stop, sensing and hardware pr_apply are replaced.
        second=cls.root/'real-start';shutil.copytree(cls.build/'source',second/'source');shutil.copytree(cls.build/'build',second/'build')
        source=second/'source';library=second/'build/flex/sim/library';adapter=library/'lib/f64.flex';text=adapter.read_text()
        old=str(cls.build/'source/core/words.flex');new=str(source/'core/words.flex')
        if text.count(old)!=1:raise ValueError('real-start dependency shape changed')
        adapter.write_text(text.replace(old,new,1))
        (library.parent/'dependencies.flex').write_text(f'import "{library/"libs/render.flex"}";\nimport "{library/"libs/physics/physics.flex"}";\n')
        brick=source/'sim/brick-vision.flex'
        replace_function(brick,'ps_brick_detect','ps_rgb_sample','fn ps_brick_detect() { return 1; }')
        replace_function(brick,'ps_rgb_sample','ps_brick_sample','fn ps_rgb_sample() { ps_brick_frame=ps_total; return 1; }')
        camera=source/'sim/camera.flex';replace_function(camera,'ps_camera_still','ps_camera_observation','fn ps_camera_still() { return 1; }')
        agent=source/'sim/agent.flex'
        replace_function(agent,'ps_physical_stop_before_handoff','ps_physical_abort','fn ps_physical_stop_before_handoff() { return 1; }')
        replace_function(agent,'ps_physical_halt','ps_physical_io','fn ps_physical_halt() { ps_physical_owner=2; ps_physical_ack=6; return 0; }')
        app=source/'runtime/app.flex';replace_function(app,'pr_apply','pr_wire','fn pr_apply(app,command,values,now) { if command!=1 || load64(values)!=200 { return 1; } sc_applied=sc_applied+1; return 0; }')
        main=source/'sim/main.flex';text=main.read_text()
        if text.count('global ps_robot = 0;')!=1 or text.count('fn main(argc, argv) {')!=1:raise ValueError('real-start main shape changed')
        text=text.replace('global ps_robot = 0;','global sc_applied=0;\nglobal ps_robot = 0;',1).replace('fn main(argc, argv) {','fn sc_original_main(argc, argv) {',1)
        main.write_text(text+'\n'+(HERE/'test_collect_start.flex').read_text())
        cls.start_binary=cls.root/'real-start-probe';built=subprocess.run([str(prepare.COMPILER),str(main),'-o',str(cls.start_binary)],cwd=ROOT,capture_output=True,text=True,timeout=120)
        if built.returncode:raise RuntimeError(built.stdout+'\n'+built.stderr)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_actual_search_handler_and_gate_with_sensor_mocks(self):
        result=subprocess.run([str(self.binary)],cwd=ROOT,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
        self.assertIn('Physical search-only CPU dispatch probe passed',result.stdout)

    def test_real_collector_start_retains_unknown_floor_and_no_target(self):
        result=subprocess.run([str(self.start_binary)],cwd=ROOT,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
        self.assertIn('Physical real collector-start CPU probe passed',result.stdout)


if __name__=='__main__':unittest.main()

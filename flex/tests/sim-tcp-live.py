#!/usr/bin/env python3
"""Check that TCP displays stay live while policy camera observations are frozen."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[2]


def native(directory):
    source = (ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)', 'fn ps_application_main(argc, argv)')
    source = re.sub(r'^import "([^"]+)";', lambda m: 'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';', source, flags=re.MULTILINE)
    source += r'''
fn main(argc, argv) {
    if !pl_init() { return 1; } h_environment(argc, argv);
    if !ps_catalog_load() || !ps_case_load(ps_case_find("ball-into-bin")) || !ps_model_load("build/flex/sim/puppybot.bin") { return 2; }
    ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);ps_json=alloc(16384);ps_builder=alloc(32);
    pb_config_default(ps_config);pb_vset(ps_config+40,2,5);ps_previews=0;ps_tcp_view=1;ps_case_camera=1;
    if !ps_reset() { return 3; } ps_render_init(1);
    let prefix=load64(argv+8);if !ps_tick(1) || !ps_rgb_sample() { return 4; }
    let samples=ps_brick_samples;let frame=ps_brick_frame;let dock=ps_dock_seen;
    ps_frame();if !ps_capture(h_cat(prefix,"-first.png")) { return 5; }
    while ps_total<120 { if !ps_tick(1) { return 6; } }
    ps_frame();if !ps_capture(h_cat(prefix,"-case.png")) { return 7; }
    if ps_brick_samples!=samples || ps_brick_frame!=frame || ps_dock_seen!=dock { return 8; }
    ps_case_camera=0;ps_frame();if !ps_capture(h_cat(prefix,"-reference.png")) { return 9; }ps_case_camera=1;
    ps_previews=1;ps_preview_next=0;ps_preview_poll();
    let targets=alloc(32);let i=0;while i<4 { store64(targets+i*8,load64(ps_plant+128+i*64+16)-40);i=i+1; }
    if pr_apply(ps_app,5,targets,ps_time) { return 10; }
    while ps_total<240 { if !ps_tick(0) { return 11; } }
    // Even a background poll scheduled far ahead cannot freeze a drawn frame.
    ps_preview_next=pl_now()+10000;ps_frame();if !ps_capture(h_cat(prefix,"-panel.png")) { return 12; }
    if load64(ps_preview_contexts+8)!=ps_total { return 13; }
    if ps_brick_samples!=samples || ps_brick_frame!=frame || ps_dock_seen!=dock { return 14; }
    pl_builder(ps_builder,ps_json,16384);pl_text(ps_builder,"{\"policySamples\":");pl_int(ps_builder,samples);pl_text(ps_builder,",\"policyFrame\":");pl_int(ps_builder,frame);pl_text(ps_builder,",\"finalStep\":");pl_int(ps_builder,ps_total);pl_text(ps_builder,"}\n");pl_print(1,ps_json);
    ps_render_close();ph_world_close(ps_physics);return 0;
}
'''
    entry, binary = directory/'live-camera.flex', directory/'live-camera'
    entry.write_text(source)
    compiler = os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT/'build/flex/pup-compiler'))
    subprocess.run([compiler, str(entry), '-o', str(binary)], cwd=ROOT, check=True)
    return binary


def inset(path):
    metadata = json.loads(Path(str(path)+'.tcp.camera.json').read_text())
    with Image.open(path) as image:
        width, height = metadata['width'], metadata['height']
        return image.convert('RGB').crop((image.width-width-20, 20, image.width-20, 20+height)), metadata


def check(directory):
    binary = native(directory)
    prefix = directory/'view'
    result = subprocess.run([str(binary), str(prefix)], cwd=ROOT, capture_output=True, text=True, timeout=30)
    (directory/'run.log').write_text(result.stdout+result.stderr)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    state = json.loads(result.stdout.strip().splitlines()[-1])
    assert state == dict(policySamples=1, policyFrame=1, finalStep=240)
    first, initial = inset(directory/'view-first.png')
    current, metadata = inset(directory/'view-case.png')
    reference, _ = inset(directory/'view-reference.png')
    assert initial['frameId'] == 1 and metadata['frameId'] == 120
    assert first.tobytes() != current.tobytes(), 'case inset retained the frozen policy image'
    assert ImageChops.difference(current, reference).getbbox() is None, 'case inset differs from the current camera view'
    observation = json.loads((directory/'view-case.png.sensor.camera.json').read_text())
    assert observation['frameId'] == 1, 'display refreshed the policy observation'
    panel = json.loads((directory/'view-panel.png.views.json').read_text())
    assert panel['views'][0]['frameId'] == 240
    receipt = dict(passed=True, policySamples=1, policyObservationStayedAtFrame=1,
                   movingCaseInsetFrame=120, currentPanelFrame=240,
                   currentInsetMatchesLiveReference=True)
    (directory/'audit.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print('Live TCP display passed: moving case inset matches the current camera; drawn panel bypasses the background timer; policy RGB and box freshness remain unchanged', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output:
        args.output.mkdir(parents=True, exist_ok=False)
        check(args.output.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix='tcp-live-', dir=ROOT/'build/flex/sim') as temporary:
            check(Path(temporary))


if __name__ == '__main__':
    main()

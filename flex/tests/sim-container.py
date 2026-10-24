#!/usr/bin/env python3
"""Push a real compound box with the rover; check friction, rigidity and cargo."""
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('box_checks', Path(__file__).with_name('sim-box.py'))
box = importlib.util.module_from_spec(spec)
spec.loader.exec_module(box)


def rotation(q):
    x,y,z,w = q
    return [[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
            [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
            [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]]


def rigid(container):
    assert container['dynamic'] and container['massKg'] == 0.3
    assert len(container['surfaces']) == 5 and {s['body'] for s in container['surfaces']} == {container['body']}
    matrix = rotation(container['quaternion'])
    offsets = [(0,0,.004),(-.084,0,.053),(.084,0,.053),(0,-.084,.053),(0,.084,.053)]
    for surface, local in zip(container['surfaces'], offsets):
        expected = [container['position'][i]+sum(matrix[i][j]*local[j] for j in range(3)) for i in range(3)]
        assert math.dist(expected, surface['centre']) < 1e-6, (expected,surface)


def push(directory, name, throttle, offset=0, cargo=False):
    scene = box.Scene(directory, name, [.35,offset,0], dynamic=True)
    try:
        if cargo:
            definition = json.loads((scene.work/'fixture.json').read_text())
            definition['objects'][0]['position'] = [.35,offset,.024]
            (scene.work/'fixture.json').write_text(json.dumps(definition))
            scene.request('/api/sim/cases/'+name,{})
            scene.request('/api/sim/reset',{})
        initial = scene.wait(lambda s:s['step']>=40)
        start = initial['case']['container']
        rigid(start)
        assert start['settled'] and abs(start['position'][2]) < .001
        deadline = time.monotonic()+8
        while True:
            scene.request('/api/drive',{'throttle':throttle,'steering':0})
            time.sleep(.04)
            state = scene.request('/api/sim/state')
            rigid(state['case']['container'])
            assert not state['blocked'] and state['physicsFault']==0
            if (not offset and state['case']['container']['position'][0] > .40) or (offset and abs(state['case']['container']['quaternion'][2]) > .02):
                break
            assert time.monotonic()<deadline, state
        scene.request('/api/drive/stop',{})
        stopped = scene.request('/api/sim/state')
        settled = scene.wait(lambda s:s['case']['container']['settled'])
        end = settled['case']['container']
        rigid(end)
        assert math.dist(end['position'][:2],start['position'][:2]) > (.005 if offset else .05)
        assert math.dist(end['velocity'],[0,0,0]) < .02
        assert abs(end['position'][2]) < .002
        if cargo:
            assert settled['case']['objects'][0]['inside'], settled['case']
            assert settled['case']['objects'][0]['position'][0] > .39
        if offset:
            assert abs(end['quaternion'][2]) > .001, end
        replay = scene.request('/api/sim/reset',{})
        assert abs(replay['case']['container']['position'][0]-.35) < 1e-6
        assert math.dist(replay['case']['container']['velocity'],[0,0,0]) == 0
        print(name+': physical movement, rigid walls, settling and reset checked',flush=True)
        return {'speed':stopped['case']['container']['velocity'][0],
                'coast':end['position'][0]-stopped['case']['container']['position'][0],
                'yaw':end['quaternion'][2]}
    finally:
        scene.close()


def main():
    with tempfile.TemporaryDirectory(prefix='sim-container-',dir=ROOT/'build/flex/sim') as temp:
        directory = Path(temp)
        gentle = push(directory,'gentle',20)
        hard = push(directory,'hard',100)
        assert hard['speed'] > gentle['speed']*3
        assert hard['coast'] > gentle['coast']+.005,(gentle,hard)
        push(directory,'off-centre',100,offset=.15)
        push(directory,'loaded',100,cargo=True)
    print('Dynamic container checks passed: contacts, impact speed/friction, rigid compound surfaces, off-centre rotation, moving-frame cargo and reset')


if __name__=='__main__':
    main()

#!/usr/bin/env python3
"""Separate normal Puppybot controller driving the rendered world over a PTY."""
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import signal
import subprocess
import tempfile
import time

from runtime import ROOT, Runtime, WebSocket, request, wait_online, check
from dashboard import Dashboard
import runtime

COMPILER = os.environ.get('FLEXSCRIPT_COMPILER') or shutil.which('flexscript') or str(ROOT.parent/'flexscript/build/flex')
ENV = {k: v for k, v in os.environ.items() if not k.startswith('PUPPYBOT_')}


class World:
    def __init__(self, directory, name='world', options=(), rendered=False):
        self.log = directory/(name+'.log')
        self.output = self.log.open('w')
        args = [COMPILER, 'run', str(ROOT/'simulator.flex')]
        args += ['--steps', '180', '--capture', str(directory/(name+'.png'))] if rendered else ['--headless']
        args += list(options)
        env = dict(ENV)
        if rendered:
            env.update(SDL_VIDEODRIVER='offscreen')
        self.process = subprocess.Popen(args, cwd=ROOT, env=env, stdout=self.output, stderr=subprocess.STDOUT)
        deadline = time.monotonic()+30
        while True:
            text = self.log.read_text()
            port = re.search(r'robot API port (\d+)', text)
            command = re.search(r'^  (flexscript run puppybot.flex .+)$', text, re.M)
            if port and command:
                self.port = int(port[1]); self.command = shlex.split(command[1])
                self.device = self.command[self.command.index('--servo-device')+1]
                break
            if self.process.poll() is not None or time.monotonic() >= deadline:
                self.process.kill(); self.process.wait(); self.output.close()
                raise AssertionError(text)
            time.sleep(.02)
        check('--virtual-bus' in self.command, 'printed controller command selects explicit PTY peripherals')

    def state(self):
        return request(self.port, '/api/sim/state')[1]

    def await_state(self, predicate, message, timeout=4):
        end = time.monotonic()+timeout
        while time.monotonic() < end:
            value = self.state()
            if predicate(value):
                return value
            time.sleep(.025)
        raise AssertionError((message, self.state(), self.log.read_text()[-1000:]))

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=10); self.output.close()
        check(self.process.returncode == 0, ('world clean shutdown', self.log.read_text()[-1000:]))


class SourceController(Runtime):
    def __init__(self, world):
        args = [COMPILER, *world.command[1:], '--bind', '127.0.0.1:0']
        self.process = subprocess.Popen(args, cwd=ROOT, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        ready, _, _ = select.select([self.process.stdout], [], [], 10)
        if not ready:
            self.process.kill(); self.process.communicate()
            raise AssertionError('source controller startup timeout')
        line = self.process.stdout.readline(); found = re.search(r'port (\d+)', line)
        if not found:
            self.process.kill(); _, error = self.process.communicate()
            raise AssertionError((line, error))
        self.port = int(found[1])


def pair(directory):
    world = World(directory)
    controller = SourceController(world)
    try:
        initial = wait_online(controller.port)
        ui = Dashboard(controller.port)
        check('Simulator' in ui.html, 'dashboard identifies the virtual peripheral bus')
        check(initial['control']['state'] == 'monitor', 'normal guarded controller starts in monitor')
        state = world.state()
        check(state['controller'] is None and state['externalSerial']['device'] == world.device, '3D process has no active internal controller')
        check(state['externalSerial']['serialPackets'] > 0, 'normal firmware exchanges serialized sensor requests')
        check(ui.action('jog', 11, lease=10)[0] == 409, 'monitor cannot drive external world')
        # Scene API cannot compete with the external controller.
        for path, body in [('/api/drive', {'action':'forward'}), ('/api/arm/joints/0/spin', {'direction':1}), ('/api/sim/pickup', {}), ('/api/sim/cases/ball-into-bin', {})]:
            check(request(world.port, path, body)[0] == 409, 'internal motion/policy API disabled in external mode')
        ws=WebSocket(world.port)
        try:
            opcode,body=ws.receive();check(opcode==8 and body[:2]==b'\x03\xf0','simulator rejects wire control with policy close1008')
        finally:ws.close()
        original_tick = state['ticks'][0]; original_tcp = state['tcp']
        check(ui.action('enable')[0] == 200, 'dashboard explicitly enables serial hardware adapter')
        check(ui.action('jog', 11, lease=11)[0] == 200, 'arm press through normal dashboard')
        for _ in range(3):
            time.sleep(.12); check(ui.action('renew', 11, lease=11)[0] == 200, 'arm hold renewal across processes')
        moved = world.await_state(lambda s:s['ticks'][0] != original_tick, 'world encoder did not move')
        check(math.dist(moved['tcp'], original_tcp) > .005, 'URDF/TCP geometry follows serial encoder motion')
        check(ui.action('release', 11, lease=11)[0] == 200, 'arm release')
        time.sleep(.25)
        settled = world.state()['ticks']; time.sleep(.2)
        check(world.state()['ticks'] == settled, 'world arm settles after serialized stop')
        # DC motor IDs overlap arm IDs; the PTY-only sideband keeps them separate.
        before = world.state()
        check(ui.action('jog', 2, lease=12)[0] == 200, 'drive reverse press')
        for _ in range(3):
            time.sleep(.12); check(ui.action('renew', 2, lease=12)[0] == 200, 'drive hold renewal')
        driven = world.await_state(lambda s:s['pose'][0] < before['pose'][0]-.035, 'vehicle did not follow serial drive outputs')
        check(driven['ticks'] == before['ticks'], 'DC drive does not alias arm servo IDs')
        check(ui.action('release', 2, lease=12)[0] == 200, 'drive release')
        time.sleep(.15); pose = world.state()['pose']; time.sleep(.2)
        check(world.state()['pose'] == pose, 'vehicle stops on button release')
        check(ui.action('jog', 2, lease=13)[0] == 200, 'abandoned drive starts')
        world.await_state(lambda s:s['pose'] != pose, 'abandoned drive never moved')
        time.sleep(.75); pose = world.state()['pose']; time.sleep(.15)
        check(world.state()['pose'] == pose, 'controller hold lease expires in 3D world')
        check(ui.action('jog', 2, lease=17)[0] == 200, 'explicit disable scenario drive')
        time.sleep(.1);check(ui.action('disable')[0]==200,'disable normal controller outputs')
        world.await_state(lambda s:not s['externalSerial']['enabled'],'disable must reach virtual peripherals')
        pose=world.state()['pose'];time.sleep(.15);check(world.state()['pose']==pose,'disable stops vehicle')
        wait_online(controller.port);check(ui.action('enable')[0]==200,'re-enable after explicit disable')
        check(ui.action('jog', 2, lease=14)[0] == 200, 'pause scenario drive')
        time.sleep(.1); request(world.port, '/api/sim/pause', {})
        end=time.monotonic()+3
        while request(controller.port, '/api/state')[1]['control']['state'] != 'monitor':
            check(time.monotonic()<end, 'pause must disarm external controller'); time.sleep(.025)
        paused=world.state();time.sleep(.15)
        check(world.state()['timeMs'] == paused['timeMs'], 'pause freezes world clock')
        request(world.port,'/api/sim/resume',{}); wait_online(controller.port)
        check(request(controller.port,'/api/state')[1]['control']['state'] == 'monitor', 'resume never auto-enables')
        check(ui.action('enable')[0] == 200, 'explicit enable after pause')
        check(ui.action('jog', 2, lease=15)[0] == 200, 'reset scenario drive')
        time.sleep(.1);request(world.port,'/api/sim/reset',{})
        end=time.monotonic()+3
        while request(controller.port,'/api/state')[1]['control']['state'] != 'monitor':
            check(time.monotonic()<end,'reset must disarm external controller');time.sleep(.025)
        wait_online(controller.port)
        check(world.state()['pose'] == [0,0,0], 'reset restores world without old motion')
        check(request(controller.port,'/api/state')[1]['control']['state'] == 'monitor', 'reset recovery requires enable')
        check(ui.action('enable')[0] == 200, 'enable for collision scene')
        check(ui.action('jog', 1, lease=18)[0] == 200, 'forward motion into scene obstacle')
        end=time.monotonic()+4
        while not world.state()['blocked'] and time.monotonic()<end:
            time.sleep(.12);check(ui.action('renew',1,lease=18)[0]==200,'renew drive toward collision boundary')
        blocked=world.state()
        check(blocked['blocked'] and blocked['pose'][0]<.38 and blocked['physicsFault']==0,'3D collision guard stops the externally driven vehicle')
        ui.action('release',1,lease=18)
        controller.close(); controller=SourceController(world)
        check(wait_online(controller.port)['control']['state'] == 'monitor', 'controller restart reconnects to same world in monitor')
        ui=Dashboard(controller.port);check(ui.action('enable')[0] == 200,'enable for crash test')
        check(ui.action('jog',2,lease=16)[0] == 200,'drive before controller crash');time.sleep(.1)
        controller.process.kill();controller.process.communicate(timeout=5)
        world.await_state(lambda s:not s['externalSerial']['enabled'],'world peripheral lease must expire after process crash')
        pose=world.state()['pose'];time.sleep(.2)
        check(world.state()['pose'] == pose,'controller crash stops world drive')
        controller=SourceController(world);wait_online(controller.port)
        world.close()
        end=time.monotonic()+3
        while all(j['online'] for j in request(controller.port,'/api/state')[1]['arm']['joints']):
            check(time.monotonic()<end,'simulator exit must invalidate feedback');time.sleep(.025)
        check(request(controller.port,'/api/control/enable',{})[0] == 409,'disconnected simulator cannot enable')
    finally:
        if controller.process.poll() is None:controller.close()
        if world.process.poll() is None:world.close()


def faults(directory):
    for name,options in [('hot',['--temperature','81']),('jam',['--jam','0'])]:
        world=World(directory,name,options=options);controller=SourceController(world)
        try:
            wait_online(controller.port);ui=Dashboard(controller.port)
            if name=='hot':
                check(ui.action('enable')[0] == 409,'3D simulated hot feedback blocks enable')
            else:
                tick=world.state()['ticks'][0];check(ui.action('enable')[0]==200,'jam explicit enable')
                check(ui.action('jog',11,lease=20)[0]==200,'jam drive command')
                end=time.monotonic()+3;fault=None
                while time.monotonic()<end and fault!='stall':
                    time.sleep(.1);ui.action('renew',11,lease=20)
                    fault=request(controller.port,'/api/state')[1]['arm']['joints'][0]['fault']
                check(fault=='stall' and world.state()['ticks'][0]==tick,'normal firmware detects jam in 3D plant')
                check(ui.action('renew',11,lease=20)[0]==409,'jam remains latched')
        finally:controller.close();world.close()


def ordinary_stservo(directory):
    world = World(directory, 'ordinary-servo')
    controller = Runtime(ROOT/'puppybot.json', world.device)
    try:
        wait_online(controller.port)
        tick = world.state()['ticks'][0]
        check(request(controller.port, '/api/control/enable', {})[0] == 200, 'ordinary serial controller enable')
        check(request(controller.port, '/api/arm/joints/0/spin', {'direction': 1})[0] == 200, 'arm needs only standard STServo traffic')
        world.await_state(lambda s:s['ticks'][0] != tick, 'standard STServo controller did not move arm')
        check(request(controller.port, '/api/arm/stop', {})[0] == 200, 'ordinary serial stop')
        pose = world.state()['pose']
        request(controller.port, '/api/drive', {'action': 'back'})
        time.sleep(.2)
        check(world.state()['pose'] == pose, 'vehicle requires the explicit virtual peripheral adapter')
    finally:
        controller.close()
        world.close()


def rendering(directory):
    world=World(directory,'rendered',rendered=True);controller=SourceController(world)
    try:
        wait_online(controller.port);ui=Dashboard(controller.port);check(ui.action('enable')[0]==200,'rendered world enable')
        check(ui.action('jog',11,lease=30)[0]==200,'rendered arm motion');time.sleep(.25);ui.action('release',11,lease=30)
        check(ui.action('jog',2,lease=31)[0]==200,'rendered drive motion');time.sleep(.25);ui.action('release',2,lease=31)
        world.process.wait(timeout=20)
        image=directory/'rendered.png'
        check(image.exists() and image.stat().st_size>10000,'3D renderer exports controlled scene')
        shutil.copyfile(image,ROOT/'build/flex/sim/external-serial.png')
    finally:
        controller.close();world.close()


def main():
    subprocess.run([COMPILER,'run',str(ROOT/'puppybot.flex'),'--help'],cwd=ROOT,env=ENV,capture_output=True,check=True,timeout=10)
    denied=subprocess.run([str(ROOT/'build/flex/puppybot-runtime'),'--virtual-bus','--servo-device','/dev/ptmx','--config',str(ROOT/'puppybot.json')],cwd=ROOT,env=ENV,capture_output=True,text=True,timeout=5)
    check(denied.returncode==2 and 'slave PTY' in denied.stderr,'virtual output adapter rejects non-slave terminals before sending packets')
    with tempfile.TemporaryDirectory(prefix='sim-serial-',dir=ROOT/'build/flex/sim') as temporary:
        directory=Path(temporary);pair(directory);faults(directory);ordinary_stservo(directory);rendering(directory)
    print(f'3D external serial: {runtime.CHECKS} source/process/PTY/control/fault/render checks passed')


if __name__=='__main__':main()

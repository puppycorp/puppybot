#!/usr/bin/env python3
"""Monolith actions/SSE and expiring motion leases on fake and PTY hardware."""
import http.client
import json
from pathlib import Path
import re
import socket
import tempfile
import time
from urllib.parse import urlencode

from runtime import Runtime, ServoEmulator, check, request, wait_for, wait_online
import runtime

ROOT = Path(__file__).resolve().parents[2]


class Dashboard:
    def __init__(self, port):
        self.port = port
        status, self.html = self.get('/')
        check(status == 200, 'dashboard SSR')
        found = re.search(r'name="monolith-token" content="([a-f0-9]{32})"', self.html)
        check(found is not None, 'Monolith action token')
        self.token = found[1]

    def get(self, path):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        conn.request('GET', path)
        response = conn.getresponse()
        result = response.status, response.read().decode()
        conn.close()
        return result

    def action(self, name, id=None, token=None, origin=None, **fields):
        fields.update(action=name, token=self.token if token is None else token)
        if id is not None:
            fields['id'] = id
        headers = {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'}
        if origin:
            headers['Origin'] = origin
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        conn.request('POST', '/action', urlencode(fields), headers)
        response = conn.getresponse()
        result = response.status, json.loads(response.read())
        conn.close()
        return result

    def state(self):
        return request(self.port, '/api/state')[1]

    def events(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        conn.request('GET', '/events')
        response = conn.getresponse()
        check(response.status == 200 and response.getheader('Content-Type') == 'text/event-stream', 'Monolith SSE')
        return conn, response


def event(response):
    while True:
        line = response.fp.readline().decode()
        if not line:
            raise EOFError('SSE stream closed')
        if line.startswith('data: '):
            return json.loads(line[6:])


def fake_dashboard(directory):
    path = directory/'dashboard.json'
    controller = Runtime(path)
    streams = []
    try:
        wait_online(controller.port)
        ui = Dashboard(controller.port)
        check('PuppyBot dashboard' in ui.html and 'data-mkey=' in ui.html, 'server rendered declarative dashboard')
        check('Drive control' in ui.html and 'Arm control' in ui.html and 'TCP jog' in ui.html, 'controller panels')
        check(ui.get('/client.js')[0] == 200 and ui.get('/style.css')[0] == 200, 'embedded assets')
        check('EventSource' in ui.get('/client.js')[1], 'upstream Monolith browser adapter')
        check(ui.action('jog', 1, token='invalid', lease=1)[0] == 403, 'invalid token cannot move')
        check(ui.action('jog', 1, origin='http://elsewhere.invalid', lease=1)[0] == 403, 'cross-origin form rejected')
        check(not ui.state()['drive']['active'], 'rejected actions have no movement side effect')
        first_conn, first = ui.events(); streams.append(first_conn)
        second_conn, second = ui.events(); streams.append(second_conn)
        check(event(first)['reset'] and event(second)['reset'], 'each browser receives reconnect snapshot')
        check(ui.action('speed', speed='275')[0] == 200, 'Monolith numeric form reaches API')
        check(ui.state()['ui']['armSpeed'] == 275, 'shared speed selection')
        check(ui.action('speed', speed='x')[0] == 400, 'invalid numeric form rejected')
        check(ui.action('speed', speed='1e999')[0] == 400, 'overflow form rejected')
        check(ui.action('frame', frame='tool')[0] == 200 and ui.state()['ui']['tcpFrame'] == 'Tool', 'TCP frame form')
        revisions = []
        for response in [first, second]:
            found = False
            for _ in range(10):
                update = event(response)
                revisions.append(update['revision'])
                if '275' in json.dumps(update):
                    found = True
                    break
            check(found, 'speed SSE patch reaches each tab')
        check(ui.action('jog', 1, lease=101)[0] == 200, 'press starts drive')
        check(ui.state()['drive']['active'], 'pressed drive is moving')
        check(ui.action('jog', 2, lease=202)[0] == 409, 'second tab cannot take over a held button')
        check(ui.action('release', 1, lease=202)[0] == 200 and ui.state()['drive']['active'], 'other tab release cannot stop owner')
        for _ in range(5):
            time.sleep(.12)
            check(ui.action('renew', 1, lease=101)[0] == 200, 'held lease renewal')
        check(ui.state()['drive']['active'], 'hold lasts beyond watchdog with renewals')
        check(ui.action('release', 1, lease=101)[0] == 200 and not ui.state()['drive']['active'], 'release immediately stops drive')
        check(ui.action('renew', 1, lease=101)[0] == 409, 'late renewal cannot restart released motion')
        check(ui.action('jog', 1, lease=303)[0] == 200, 'second press')
        wait_for(lambda: not ui.state()['drive']['active'], 'abandoned fake UI hold never expired')
        check(ui.action('renew', 1, lease=303)[0] == 409, 'expired lease cannot be revived')
        check(ui.action('jog', 1, lease=404)[0] == 200, 'new press after expiration')
        request(controller.port, '/api/drive/stop', {})
        check(ui.action('renew', 1, lease=404)[0] == 409, 'external API stop revokes UI lease')
        check(ui.action('angles', yawDeg='0', shoulderDeg='90', elbowDeg='0', wristDeg='0')[0] == 200, 'joint target form')
        check(ui.action('stop')[0] == 200, 'global stop')
        check(ui.action('limits', 1, minTick=2, maxTick=4090)[0] == 200, 'fake limit editor')
        check(ui.action('reference', 1, angleDeg='12.5')[0] == 200, 'fake reference editor')
        check(ui.action('save')[0] == 200 and path.exists(), 'calibration save')
        # A subscriber that never reads must not hold up control or the watchdog.
        slow = socket.create_connection(('127.0.0.1', controller.port), timeout=2)
        streams.append(slow)
        slow.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
        slow.sendall(f'GET /events HTTP/1.1\r\nHost: 127.0.0.1:{controller.port}\r\n\r\n'.encode())
        check(ui.action('jog', 1, lease=505)[0] == 200, 'motion with slow SSE subscriber')
        wait_for(lambda: not ui.state()['drive']['active'], 'slow subscriber blocked lease expiry')
        check(request(controller.port, '/health')[0] == 200, 'listener remains responsive')
    finally:
        for stream in streams:
            stream.close()
        controller.close()


def physical_dashboard(directory):
    config = json.loads((ROOT/'puppybot.json').read_text())
    path = directory/'physical.json'; path.write_text(json.dumps(config))
    emulator = ServoEmulator(config)
    controller = Runtime(path, emulator.path)
    try:
        wait_online(controller.port)
        ui = Dashboard(controller.port)
        check('Monitor' in ui.html and 'restart' in ui.html, 'hardware monitor and locked calibration in SSR')
        check(ui.action('jog', 11, lease=1001)[0] == 409, 'dashboard jog rejected before enable')
        check(not any(emulator.speeds.values()), 'monitor UI never drives servos')
        check(ui.action('limits', 1, minTick=0, maxTick=4095)[0] == 409, 'UI cannot bypass hardware limit lock')
        check(ui.action('reference', 1, angleDeg=0)[0] == 409, 'UI cannot bypass hardware calibration lock')
        check(ui.action('enable')[0] == 200, 'explicit dashboard enable')
        check(ui.action('jog', 11, lease=1002)[0] == 200, 'hardware joint press')
        wait_for(lambda: emulator.speeds[1] > 0, 'UI press did not reach PTY servo')
        for _ in range(6):
            time.sleep(.1)
            check(ui.action('renew', 11, lease=1002)[0] == 200, 'hardware renew through guarded API')
        check(emulator.speeds[1] > 0, 'hardware hold beyond500ms')
        check(ui.action('release', 11, lease=1002)[0] == 200, 'hardware release')
        wait_for(lambda: emulator.speeds[1] == 0, 'UI release did not stop servo')
        check(ui.action('jog', 11, lease=1005)[0] == 200, 'hardware stop-button press')
        wait_for(lambda: emulator.speeds[1] > 0, 'stop-button press never moved')
        check(ui.action('stop')[0] == 200, 'hardware dashboard stop all')
        wait_for(lambda: emulator.speeds[1] == 0, 'stop all did not cancel physical output')
        check(ui.action('renew', 11, lease=1005)[0] == 409, 'stop all revokes hold')
        check(ui.action('jog', 11, lease=1003)[0] == 200, 'hardware abandoned press')
        wait_for(lambda: emulator.speeds[1] > 0, 'abandoned press never moved')
        wait_for(lambda: emulator.speeds[1] == 0, 'abandoned hardware UI lease did not expire')
        check(ui.action('jog', 11, lease=1004)[0] == 200, 'thermal test press')
        wait_for(lambda: emulator.speeds[1] > 0, 'thermal test press never moved')
        emulator.temperatures[3] = 81
        wait_for(lambda: emulator.speeds[1] == 0, 'thermal interlock failed during UI jog')
        wait_for(lambda: ui.state()['control']['state'] == 'monitor', 'thermal UI monitor recovery')
        check(ui.action('renew', 11, lease=1004)[0] != 200, 'thermal stop cannot be renewed')
        check(ui.action('enable')[0] == 409, 'UI hot enable rejected')
        emulator.temperatures[3] = 25
        wait_for(lambda: ui.state()['control']['temperatures'][2]['temperatureC'] == 25, 'cool sample')
        check(ui.state()['control']['state'] == 'monitor', 'cooling never auto-enables dashboard')
        check(ui.action('enable')[0] == 200, 'UI explicit re-enable after cooling')
        check(ui.action('disable')[0] == 200, 'dashboard disable')
        wait_for(lambda: ui.state()['control']['state'] == 'monitor', 'dashboard disable finishes in monitor')
    finally:
        controller.close(); emulator.close()


def main():
    with tempfile.TemporaryDirectory(prefix='puppybot-dashboard-') as temporary:
        directory = Path(temporary)
        fake_dashboard(directory)
        physical_dashboard(directory)
    print(f'Monolith dashboard: {runtime.CHECKS} action/SSE/lease/PTY checks passed')


if __name__ == '__main__':
    main()

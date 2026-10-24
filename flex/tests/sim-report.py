#!/usr/bin/env python3
"""Check the report's real result matrix, embedded evidence and offline interactions."""
import base64
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import struct
import subprocess
import zlib

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT/'build/flex/sim/stress/highlights-site/dist/index.html'


class Structure(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.references = []
        self.payload = ''
        self.in_payload = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            assert attrs['id'] not in self.ids, 'duplicate element ID'
            self.ids.add(attrs['id'])
        if tag == 'script':
            assert 'src' not in attrs, 'page depends on an external script'
            self.in_payload = attrs.get('id') == 'report-data'
        for key in ('href', 'aria-labelledby'):
            if key in attrs:
                self.references.append((key, attrs[key]))
        if tag == 'img':
            assert 'alt' in attrs

    def handle_endtag(self, tag):
        if tag == 'script':
            self.in_payload = False

    def handle_data(self, value):
        if self.in_payload:
            self.payload += value


def main():
    source = PAGE.read_text()
    assert not any(token in source for token in ('__STYLE__', '__SCRIPT__', '__PAYLOAD__'))
    parsed = Structure()
    parsed.feed(source)
    data = json.loads(parsed.payload)
    report = data['report']
    assert len(report['runs']) == 20 and report['validExperiment'] and report['complete']
    assert sum(run['passed'] for run in report['runs']) == 13
    for kind, value in parsed.references:
        if kind == 'aria-labelledby':
            assert all(name in parsed.ids for name in value.split())
        elif value.startswith('#'):
            assert value[1:] in parsed.ids
        else:
            raise AssertionError('page navigates away from its self-contained content')
    script = (ROOT/'flex/sim/report/report.js').read_text()
    assert set(re.findall(r"\$\('([^']+)'\)", script)) <= parsed.ids
    assert len(data['images']) == 60
    for value in data['images'].values():
        encoded = value.removeprefix('data:image/png;base64,')
        png = base64.b64decode(encoded, validate=True)
        assert png[:8] == b'\x89PNG\r\n\x1a\n'
        width, height, depth, colour = struct.unpack('>IIBB', png[16:26])
        assert (width, height) in ((1280, 800), (640, 480)) and depth == 8 and colour == 2
        cursor, compressed = 8, bytearray()
        while cursor < len(png):
            length = struct.unpack('>I', png[cursor:cursor+4])[0]
            chunk = png[cursor+4:cursor+8+length]
            assert zlib.crc32(chunk) == struct.unpack('>I', png[cursor+8+length:cursor+12+length])[0]
            if chunk[:4] == b'IDAT':
                compressed.extend(chunk[4:])
            cursor += 12+length
        pixels = zlib.decompress(compressed)
        stride = width*3+1
        assert len(pixels) == stride*height and all(pixels[row*stride] <= 4 for row in range(height))
    for run in report['runs']:
        name = run['directory']
        assert name in data['fixtures'] and name in data['sensor']
        sensor = data['sensor'][name]
        assert sensor['view'] == 'tcp'
        assert all(len(detection['box']) == 4 for detection in sensor['detections'])
        assert Path(run['replay']).is_file()
    test = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const sandbox = {module: {exports: {}}};
vm.runInNewContext(fs.readFileSync('flex/sim/report/report.js', 'utf8'), sandbox);
const m = sandbox.module.exports;
const r = JSON.parse(fs.readFileSync('build/flex/sim/stress/results/report.json', 'utf8')).runs;
assert.equal(m.totals(r).passed, 13);
assert.equal(m.totals(r).failed, 7);
assert.equal(m.totals(r).errors, 0);
assert.equal(m.filterRuns(r, {status:'failed', challenge:'all', seed:'all'}).length, 7);
assert.equal(m.filterRuns(r, {status:'passed', challenge:'touching', seed:'all'}).length, 6);
assert.equal(m.filterRuns(r, {status:'failed', challenge:'touching', seed:'42'}).length, 0);
assert.equal(m.filterRuns(r, {status:'failed', challenge:'occlusion', seed:'42'}).length, 3);
assert.equal(m.filterRuns(r, {status:'passed', challenge:'occlusion', seed:'43'}).length, 3);
assert.equal(m.matrix(r).length, 10);
assert(m.matrix(r).every(row => row.runs.length === 2));
for (const run of r) {
    assert(m.title(run).length > 0 && m.variant(run).length > 0);
    assert(m.explanation(run).length > 30);
    if (run.challenge === 'distractors' && run.level === 3) assert(run.metrics.nonTargetSelections > 0);
    if (run.challenge === 'occlusion' && !run.passed) assert(run.metrics.blockedDriveSteps > 0);
}
assert.equal(m.escape('<script>'), '&lt;script&gt;');
console.log('Real-data filters, empty states, result matrix, failure descriptions and counters passed');
"""
    subprocess.run(['node', '-e', test], cwd=ROOT, check=True)
    print('Report checks passed: 20 audited runs, 60 valid embedded PNGs, matching sensor views, offline page, accessible IDs and replay paths')


if __name__ == '__main__':
    main()

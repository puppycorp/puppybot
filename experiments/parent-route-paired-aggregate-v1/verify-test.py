#!/usr/bin/env python3
"""Small independent fixtures for paired-dataset byte verification."""
import importlib.util
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('paired_verify', HERE / 'verify.py')
verify = importlib.util.module_from_spec(spec); spec.loader.exec_module(verify)
LENGTH, IMAGE, MAP, MEMORY, OLD, FIT, CUTOFF = 4, 5, 3, 2, 4, 2, 2


def header(magic, n, fit, length=LENGTH):
    return struct.pack('<8s3q', magic, n, fit, length)


def action(steer, speed=1):
    return struct.pack('<2f', steer, speed)


class PairedVerificationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        stride = LENGTH * (IMAGE + 56); mstride = LENGTH * MAP
        self.base = self.root / 'base'; self.base_map = self.root / 'base-map'
        self.base.write_bytes(header(b'PVDATA04', OLD, FIT) +
                              b''.join(bytes([i + 20]) * stride for i in range(OLD)))
        self.base_map.write_bytes(header(b'PVMAP001', OLD, FIT) +
                                  b''.join(bytes([i + 40]) * mstride for i in range(OLD)))
        self.sources = [self.source(i) for i in range(2)]
        self.control = self.root / 'control'; self.control_map = self.root / 'control-map'
        self.treatment = self.root / 'treatment'; self.treatment_map = self.root / 'treatment-map'
        for path, kind in ((self.control, 'control'), (self.treatment, 'treatment')):
            base = self.base.read_bytes(); inserted = b''
            for source in self.sources:
                raw = Path(source['data']).read_bytes(); images = raw[32:32 + LENGTH * IMAGE]
                rows = raw[32 + LENGTH * IMAGE:32 + LENGTH * (IMAGE + 44)]
                result = b''
                for i in range(LENGTH):
                    row = rows[i * 44:(i + 1) * 44]; executed = action(0)
                    label = (row[28:36] if kind == 'control' else executed) if i < CUTOFF else bytes(8)
                    result += row[:28] + label + row[36:40] + (verify.ONE if i < CUTOFF else verify.ZERO) + verify.ONE + executed
                inserted += images + result
            path.write_bytes(header(b'PVDATA04', OLD + 2, FIT + 2) + base[32:32 + FIT * stride] +
                             inserted + base[32 + FIT * stride:])
        for path in (self.control_map, self.treatment_map):
            base = self.base_map.read_bytes()
            additions = b''.join(Path(source['map']).read_bytes()[32:32 + mstride] for source in self.sources)
            path.write_bytes(header(b'PVMAP001', OLD + 2, FIT + 2) + base[32:32 + FIT * mstride] +
                             additions + base[32 + FIT * mstride:])

    def source(self, number):
        root = self.root / f'source-{number}'; root.mkdir()
        images = [bytes([number + i + 1]) * IMAGE for i in range(LENGTH)]
        maps = [bytes([(i + number) % 3]) * MAP for i in range(LENGTH)]
        cues = (0., 1., 0., 0.)
        action_bytes = action(0); teacher = [action(.6), action_bytes, action(-.6), action_bytes]
        rows = []; binary_rows = b''
        actor_record = 24 + IMAGE + (IMAGE + 7 + MEMORY) * 4 + (2 + MEMORY) * 4 + 8
        actor = header(b'PBATST01', 1, 100 + number, LENGTH) + struct.pack('<3q', IMAGE, MEMORY, actor_record)
        boundary = header(b'PBMAPB01', 1, 100 + number, LENGTH) + struct.pack('<q', 24 + MAP + 8)
        for i in range(LENGTH):
            seq, frame = i + 2, 100 + 10 * i
            feedback = struct.pack('<7f', 0, 0, 0, 0, 0, 0, cues[i])
            binary_rows += feedback + teacher[i] + verify.ZERO + verify.ONE
            normalized = b''.join(struct.pack('<f', value / 255.0) for value in images[i])
            actor += struct.pack('<3q', i, seq, frame) + images[i] + normalized + feedback + bytes(MEMORY * 4)
            actor += action_bytes + bytes(MEMORY * 4) + action_bytes
            boundary += struct.pack('<3q', i, seq, frame) + maps[i] + teacher[i]
            if i == 0: state = {'consumedIndex': 0, 'phase': 'return', 'deliveries': 0}
            elif i == 1: state = {'consumedIndex': 0, 'phase': 'delivered', 'deliveries': 1}
            else: state = {'consumedIndex': -1, 'phase': 'search', 'deliveries': 1}
            rows.append({'sequence': seq + 1, 'step': frame + 10, 'action': [0, 1],
                         'state': {'totalSteps': frame + 10, 'findReturn': state}})
        actor += struct.pack('<8sq', b'PBDONE01', LENGTH)
        boundary += struct.pack('<8sq', b'PBDONE01', LENGTH)
        ep = b''.join(images) + binary_rows; map_ep = b''.join(maps)
        (root / 'data').write_bytes(header(b'PVDATA01', 2, 1) + ep + bytes(len(ep)))
        (root / 'map').write_bytes(header(b'PVMAP001', 2, 1) + map_ep + bytes(len(map_ep)))
        (root / 'actor').write_bytes(actor); (root / 'boundary').write_bytes(boundary)
        (root / 'decisions').write_text(''.join(json.dumps(row) + '\n' for row in rows))
        (root / 'events').write_text(json.dumps({'event': 'start'}) + '\n' + json.dumps({'event': 'delivery', 'step': 2}) + '\n')
        return {'seed': 100 + number, 'episode': 0, 'cutoff': CUTOFF, **{key: root / key for key in
                ('data', 'map', 'actor', 'boundary', 'decisions', 'events')}}

    def tearDown(self):
        self.temp.cleanup()

    def check(self):
        return verify.verify(self.base, self.base_map, self.sources, self.control, self.control_map,
                             self.treatment, self.treatment_map, old_count=OLD, old_fit=FIT,
                             length=LENGTH, image=IMAGE, map_row=MAP, memory=MEMORY,
                             expected_sources=((100, 0, 2), (101, 0, 2)), aux_mask_begin=1)

    def mutate(self, path, offset, byte):
        data = bytearray(path.read_bytes()); data[offset] = byte; path.write_bytes(data)

    def test_matching_pair_preserves_baseline_and_fit_split(self):
        report = self.check()
        self.assertEqual((report['episodes'], report['fitting']), (6, 4))
        self.assertEqual(report['prefixLabelDifferences'], [1, 1])
        self.assertEqual((report['auxiliaryMaskRequirement']['episodeStartInclusive'],
                          report['auxiliaryMaskRequirement']['episodeEndExclusive']), (1, 4))
        self.assertFalse(report['trainingAuthorized'])

    def test_baseline_validation_and_added_map_corruption_rejected(self):
        stride = LENGTH * (IMAGE + 56)
        self.mutate(self.control, 32 + (FIT + 2) * stride, 0)
        with self.assertRaisesRegex(ValueError, 'preserved episode'):
            self.check()
        self.control.write_bytes(self.treatment.read_bytes())
        self.mutate(self.control_map, 32 + FIT * LENGTH * MAP, 2)
        with self.assertRaises(ValueError):
            self.check()

    def test_suffix_label_and_parent_executed_corruption_rejected(self):
        offset = 32 + FIT * LENGTH * (IMAGE + 56) + LENGTH * IMAGE
        self.mutate(self.treatment, offset + CUTOFF * 56 + 28, 1)
        with self.assertRaisesRegex(ValueError, 'paired label'):
            self.check()
        self.treatment.write_bytes(self.control.read_bytes())
        self.mutate(self.treatment, offset + 48, 1)
        with self.assertRaisesRegex(ValueError, 'paired label'):
            self.check()

    def test_source_boundary_and_companion_rejected(self):
        self.sources[0]['episode'] = 1
        with self.assertRaisesRegex(ValueError, 'source identities'):
            self.check()
        self.sources[0]['episode'] = 0
        self.mutate(self.sources[0]['actor'], 56 + 24, 255)
        with self.assertRaisesRegex(ValueError, 'actor image'):
            self.check()

    def test_hardlinked_outputs_rejected(self):
        self.treatment.unlink(); os.link(self.control, self.treatment)
        with self.assertRaisesRegex(ValueError, 'aliases'):
            self.check()

    def test_wrong_first_delivery_and_no_prefix_differences_rejected(self):
        self.sources[0]['cutoff'] = 3
        with self.assertRaisesRegex(ValueError, 'source identities'):
            self.check()
        self.sources[0]['cutoff'] = CUTOFF
        events = self.sources[0]['events']; events.write_text(json.dumps({'event': 'start'}) + '\n')
        with self.assertRaisesRegex(ValueError, 'delivery events'):
            self.check()

    def test_differences_only_after_supervised_prefix_rejected(self):
        source = self.sources[0]
        for key, offset in (('data', 32 + LENGTH * IMAGE + 28), ('boundary', 40 + 24 + MAP)):
            path = source[key]; contents = bytearray(path.read_bytes())
            contents[offset:offset + 8] = action(0); path.write_bytes(contents)
        with self.assertRaisesRegex(ValueError, 'no supervised-prefix'):
            self.check()

    def test_suffix_weight_and_validity_cannot_change(self):
        offset = 32 + FIT * LENGTH * (IMAGE + 56) + LENGTH * IMAGE
        self.mutate(self.control, offset + CUTOFF * 56 + 40, 1)
        with self.assertRaisesRegex(ValueError, 'mask, validity'):
            self.check()

    def test_parent_prefix_label_cannot_use_teacher(self):
        offset = 32 + FIT * LENGTH * (IMAGE + 56) + LENGTH * IMAGE
        data = bytearray(self.treatment.read_bytes())
        data[offset + 28:offset + 36] = action(.6)
        self.treatment.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'paired label'):
            self.check()

    def test_source_map_and_recurrent_tampering_are_rejected(self):
        self.mutate(self.sources[0]['boundary'], 40 + 24, 2)
        with self.assertRaisesRegex(ValueError, 'source map row'):
            self.check()
        self.tearDown(); self.setUp()
        record = 24 + IMAGE + (IMAGE + 7 + MEMORY) * 4 + (2 + MEMORY) * 4 + 8
        second_hidden = 56 + record + 24 + IMAGE + (IMAGE + 7) * 4
        self.mutate(self.sources[0]['actor'], second_hidden, 1)
        with self.assertRaisesRegex(ValueError, 'recurrent state'):
            self.check()



if __name__ == '__main__':
    unittest.main()

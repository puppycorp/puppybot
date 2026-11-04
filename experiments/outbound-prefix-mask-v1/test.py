#!/usr/bin/env python3
"""Small fixed-format fixtures for safe outbound-label derivation."""
import json
import importlib.util
import mmap
import pathlib
import struct
import tempfile
import types
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('prefix_mask', pathlib.Path(__file__).with_name('mask.py'))
mask = importlib.util.module_from_spec(spec); spec.loader.exec_module(mask)


def write_shard(root, name, first, fit, teacher):
    path = root / name; path.mkdir()
    count = len(first); length = mask.HORIZON
    data = bytearray(b'PVDATA01' + struct.pack('<3q', count, fit, length))
    data.extend(b'\0' * (count * length * (mask.IMAGE + mask.RAW_ROW)))
    for episode, pickup in enumerate(first):
        base = 32 + episode * length * (mask.IMAGE + mask.RAW_ROW)
        data[base:base + length * mask.IMAGE] = bytes([10 + episode + 10 * (not teacher)]) * (length * mask.IMAGE)
        run = path / f'expert-{episode}'; run.mkdir()
        rows = []
        for step in range(length):
            offset = base + length * mask.IMAGE + step * mask.RAW_ROW
            struct.pack_into('<2f', data, offset + 28, .5, -.5)
            data[offset + 40:offset + 44] = mask.ONE
            found = pickup is not None and step + 1 >= pickup
            rows.append({'action': [.5, -.5], 'state': {'findReturn': {'consumedIndex': 0 if found else -1,
                         'phase': 'return' if found else 'search', 'deliveries': 0}}})
        (run / 'decisions.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
        (run / 'result.json').write_text(json.dumps({'steps': length, 'seed': 100 + episode,
                                                    'game': 'fetch', 'controller': 'exploring fetch teacher',
                                                    'exploreTeacher': True, 'deliveries': 0,
                                                    'reaches': int(pickup is not None)}))
        (run / 'initial.json').write_text(json.dumps({'findReturn': {'consumedIndex': -1}}))
        (run / 'chase.jsonl').write_text(json.dumps({'event': 'start'}) + '\n')
    (path / 'data.bin').write_bytes(data)
    map_file = path / 'map.bin'
    map_file.write_bytes(b'PVMAP001' + struct.pack('<3q', count, fit, length) +
                         b''.join(bytes([episode + 10 * (not teacher)]) * (length * mask.MAP_ROW)
                                  for episode in range(count)))
    (path / 'report.json').write_text(json.dumps({'complete': True, 'studentDriven': not teacher,
        'teacher': 'exploring fetch teacher', 'teacherUsesCameraDetections': True,
        'teacherUsesReferenceGeometryForWallsOnly': True, 'teacherUsesTargetCoordinates': False,
        'actorUsesReferencePose': False, 'actorUsesTargetCoordinates': False,
        'seed': 100, 'episodes': count, 'trainingEpisodes': fit,
        'sequenceLength': length, 'dataSHA256': mask.sha(path / 'data.bin'), 'mapSHA256': mask.sha(map_file)}))
    return path


def aggregate(root, sources):
    pieces = []
    fits = 0
    source_data = []; maps = []
    for path in sources:
        data = (path / 'data.bin').read_bytes()
        count, fit = mask.header(data, b'PVDATA01', mask.IMAGE + mask.RAW_ROW)
        source_data.append((data, count, fit, (path / 'map.bin').read_bytes())); fits += fit
    for split in (0, 1):
        for data, count, fit, map_data in source_data:
            for episode in (range(fit) if split == 0 else range(fit, count)):
                base = 32 + episode * mask.HORIZON * (mask.IMAGE + mask.RAW_ROW)
                images = data[base:base + mask.HORIZON * mask.IMAGE]
                rows = bytearray()
                for step in range(mask.HORIZON):
                    pos = base + mask.HORIZON * mask.IMAGE + step * mask.RAW_ROW
                    raw = data[pos:pos + mask.RAW_ROW]
                    rows.extend(raw + mask.ONE + raw[28:36])
                pieces.append(images + rows)
                map_start = 32 + episode * mask.HORIZON * mask.MAP_ROW
                maps.append(map_data[map_start:map_start + mask.HORIZON * mask.MAP_ROW])
    aggregate_dir = root / 'aggregate'; aggregate_dir.mkdir()
    output = aggregate_dir / 'data.bin'
    output.write_bytes(b'PVDATA04' + struct.pack('<3q', len(pieces), fits, mask.HORIZON) + b''.join(pieces))
    map_path = aggregate_dir / 'map.bin'
    map_path.write_bytes(b'PVMAP001' + struct.pack('<3q', len(pieces), fits, mask.HORIZON) + b''.join(maps))
    return output, map_path


def teacher_identity(shard, episode):
    run = shard / ('expert-' + str(episode))
    return {'episode': episode, 'seed': 100 + episode,
            'evidence': {name: mask.sha(run / name) for name in
                         ('result.json', 'initial.json', 'chase.jsonl', 'decisions.jsonl')}}


class PrefixMaskTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = pathlib.Path(self.temp.name)
        self.patches = [mock.patch.object(mask, 'HORIZON', 5), mock.patch.object(mask, 'IMAGE', 8),
                        mock.patch.object(mask, 'MAP_ROW', 3)]
        for patch in self.patches: patch.start(); self.addCleanup(patch.stop)
        self.addCleanup(self.temp.cleanup)
        self.teacher = write_shard(self.root, 'teacher', [2, None, 5], 2, True)
        self.student = write_shard(self.root, 'student', [None, None], 1, False)
        self.data, self.map = aggregate(self.root, [self.teacher, self.student])
        self.inputs = [(self.teacher, True), (self.student, False)]

    def run_mask(self, name='derived'):
        return mask.create(self.data, self.inputs, self.root / name, self.map, min_free=0)

    def test_masks_only_after_pickup_preserves_history_and_drops_teacher_miss(self):
        original = self.data.read_bytes(); original_map = self.map.read_bytes()
        report = self.run_mask(); data = (self.root / 'derived/data.bin').read_bytes()
        mapped = (self.root / 'derived/map.bin').read_bytes()
        self.assertEqual(mask.header(data, b'PVDATA04', mask.IMAGE + mask.AGG_ROW), (4, 2))
        self.assertEqual([x['aggregateIndex'] for x in report['excludedTeacherEpisodes']], [1])
        # Input order: teacher fit 0, teacher fit 1 (excluded), student fit,
        # teacher validation, student validation. Output preserves that order.
        for target, source in enumerate([0, 2, 3, 4]):
            src = 32 + source * 5 * (mask.IMAGE + mask.AGG_ROW)
            dst = 32 + target * 5 * (mask.IMAGE + mask.AGG_ROW)
            self.assertEqual(data[dst:dst + 5 * mask.IMAGE], original[src:src + 5 * mask.IMAGE])
            self.assertEqual(mapped[32 + target * 15:32 + (target + 1) * 15], original_map[32 + source * 15:32 + (source + 1) * 15])
            for step in range(5):
                s = src + 5 * mask.IMAGE + step * 56; d = dst + 5 * mask.IMAGE + step * 56
                self.assertEqual(data[d:d + 40], original[s:s + 40])
                self.assertEqual(data[d + 44:d + 56], original[s + 44:s + 56])
                expected = mask.ZERO if source == 0 and step >= 2 else original[s + 40:s + 44]
                self.assertEqual(data[d + 40:d + 44], expected)
        self.assertEqual(self.data.read_bytes(), original)
        self.assertEqual(self.map.read_bytes(), original_map)

    def test_refuses_overwrite_bad_order_and_source_tampering(self):
        self.run_mask()
        with self.assertRaises(FileExistsError): self.run_mask()
        with self.assertRaises(ValueError): mask.create(self.data, list(reversed(self.inputs)), self.root / 'bad-order', self.map, min_free=0)
        path = self.teacher / 'expert-0/decisions.jsonl'
        rows = [json.loads(x) for x in path.read_text().splitlines()]; rows[0]['action'] = [0, 0]
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        with self.assertRaises(ValueError): self.run_mask('bad-decision')
        self.assertFalse((self.root / 'bad-decision').exists())

    def test_rejects_invalid_source_and_teacher_role(self):
        raw = self.teacher / 'data.bin'; raw.write_bytes(raw.read_bytes() + b'x')
        with self.assertRaises(ValueError): self.run_mask('bad-source')
        self.assertFalse((self.root / 'bad-source').exists())
        with self.assertRaises(ValueError): mask.create(self.data, [(self.student, True), (self.teacher, False)],
                                                       self.root / 'bad-role', self.map, min_free=0)

    def test_rejects_inconsistent_initial_or_transition(self):
        initial = self.teacher / 'expert-0/initial.json'
        initial.write_text(json.dumps({'findReturn': {'consumedIndex': 0}}))
        with self.assertRaises(ValueError): self.run_mask('bad-initial')
        initial.write_text(json.dumps({'findReturn': {'consumedIndex': -1}}))
        path = self.teacher / 'expert-0/decisions.jsonl'
        rows = [json.loads(x) for x in path.read_text().splitlines()]
        rows[1]['state']['findReturn']['phase'] = 'search'
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        with self.assertRaises(ValueError): self.run_mask('bad-transition')
        self.assertFalse((self.root / 'bad-transition').exists())

    def test_rejects_all_empty_split_and_invalid_frame(self):
        path = self.teacher / 'expert-0/decisions.jsonl'
        rows = [json.loads(x) for x in path.read_text().splitlines()]
        for row in rows:
            row['state']['findReturn']['consumedIndex'] = -1
            row['state']['findReturn']['phase'] = 'search'
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        result_path = self.teacher / 'expert-0/result.json'
        result = json.loads(result_path.read_text()); result['reaches'] = 0
        result_path.write_text(json.dumps(result))
        # A validation-only prefix must not be published as training data.
        with self.assertRaisesRegex(ValueError, 'no fitting teacher-prefix'):
            self.run_mask('drop-both')
        self.assertFalse((self.root / 'drop-both').exists())
        path = self.teacher / 'expert-2/decisions.jsonl'
        rows = [json.loads(x) for x in path.read_text().splitlines()]
        for row in rows:
            row['state']['findReturn']['consumedIndex'] = -1
            row['state']['findReturn']['phase'] = 'search'
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        result_path = self.teacher / 'expert-2/result.json'
        result = json.loads(result_path.read_text()); result['reaches'] = 0
        result_path.write_text(json.dumps(result))
        with self.assertRaisesRegex(ValueError, 'no fitting teacher-prefix'):
            self.run_mask('all-teacher-miss')
        self.assertFalse((self.root / 'all-teacher-miss').exists())
        contents = bytearray(self.data.read_bytes()); contents[32 + 5 * 8 + 44:32 + 5 * 8 + 48] = mask.ZERO
        self.data.write_bytes(contents)
        with self.assertRaises(ValueError): self.run_mask('bad-valid')

    def test_existing_mask_remains_zero_and_does_not_mask_valid_frame(self):
        contents = bytearray(self.data.read_bytes()); offset = 32 + 5 * 8 + 40
        contents[offset:offset + 4] = mask.ZERO; self.data.write_bytes(contents)
        self.run_mask('premasked')
        output = (self.root / 'premasked/data.bin').read_bytes()
        self.assertEqual(output[offset:offset + 4], mask.ZERO)
        self.assertEqual(output[offset + 4:offset + 8], mask.ONE)

    def test_readback_verifier_rejects_changed_unmasked_history(self):
        self.run_mask()
        output = self.root / 'derived/data.bin'; data = bytearray(output.read_bytes()); data[32] ^= 1
        output.write_bytes(data)
        with self.data.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as merged:
            with self.map.open('rb') as stream_map, mmap.mmap(stream_map.fileno(), 0, access=mmap.ACCESS_READ) as merged_map:
                with self.assertRaises(ValueError):
                    mask.verify_output(output, self.root / 'derived/map.bin', merged, merged_map,
                                       [(0, 2, True), (2, None, True), (3, 5, False), (4, None, False)], 2)

    def test_shuffled_aggregate_map_rejected_before_output(self):
        maps = bytearray(self.map.read_bytes()); size = mask.HORIZON * mask.MAP_ROW
        first, second = bytes(maps[32:32 + size]), bytes(maps[32 + size:32 + 2 * size])
        self.assertNotEqual(first, second)
        maps[32:32 + size] = second; maps[32 + size:32 + 2 * size] = first
        self.map.write_bytes(maps)
        with self.assertRaisesRegex(ValueError, 'map history'):
            self.run_mask('shuffled-map')
        self.assertFalse((self.root / 'shuffled-map').exists())

    def test_output_inside_input_tree_or_symlink_redirect_is_rejected(self):
        link = self.root / 'source-link'; link.symlink_to(self.teacher, target_is_directory=True)
        for output in (self.teacher / 'derived', self.data.parent / 'derived', link / 'derived'):
            with self.subTest(output=output):
                with self.assertRaisesRegex(ValueError, 'inside an input tree'):
                    mask.create(self.data, self.inputs, output, self.map, min_free=0)
                self.assertFalse(output.exists())

    def test_detached_episode_symlink_is_rejected(self):
        run = self.teacher / 'expert-0'; detached = self.root / 'detached'
        run.rename(detached); run.symlink_to(detached, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'detached teacher episode'):
            self.run_mask('detached-output')
        self.assertFalse((self.root / 'detached-output').exists())

    def test_space_drop_retains_partial_without_publishing_report(self):
        data_before = mask.sha(self.data); map_before = mask.sha(self.map)
        readings = [types.SimpleNamespace(free=10**9), types.SimpleNamespace(free=10**9),
                    types.SimpleNamespace(free=0)]
        with mock.patch.object(mask.shutil, 'disk_usage', side_effect=readings):
            with self.assertRaisesRegex(ValueError, 'below the required floor'):
                mask.create(self.data, self.inputs, self.root / 'partial', self.map, min_free=20)
        self.assertTrue((self.root / 'partial/data.bin').is_file())
        self.assertFalse((self.root / 'partial/report.json').exists())
        self.assertEqual(mask.sha(self.data), data_before); self.assertEqual(mask.sha(self.map), map_before)

    def test_explicit_selection_keeps_only_named_fitting_teacher_and_preserves_other_split(self):
        selected = {str(self.teacher.absolute()): {
            'dataSHA256': mask.sha(self.teacher / 'data.bin'),
            'reportSHA256': mask.sha(self.teacher / 'report.json'),
            'episodes': [teacher_identity(self.teacher, 0)]}}
        before = {str(path): mask.sha(path) for path in (self.data, self.map, self.teacher / 'data.bin', self.student / 'data.bin')}
        result = mask.create(self.data, self.inputs, self.root / 'selected', self.map,
                             min_free=0, teacher_selection=selected)
        self.assertEqual(result['teacherSelection'], selected)
        self.assertIs(result['selectionQualityVerified'], False)
        self.assertIs(result['trainingAuthorized'], False)
        self.assertEqual((result['outputEpisodes'], result['outputFittingEpisodes']), (3, 2))
        self.assertEqual([item['episode'] for item in result['excludedTeacherEpisodes']], [1, 2])
        self.assertTrue(all(item['reason'] == 'not_selected_fitting_teacher' for item in result['excludedTeacherEpisodes']))
        self.assertEqual([item['teacherPrefix'] for item in result['episodes']], [True, False, False])
        self.assertEqual([item['fit'] for item in result['episodes']], [True, True, False])
        self.assertEqual({str(path): mask.sha(path) for path in (self.data, self.map, self.teacher / 'data.bin', self.student / 'data.bin')}, before)

    def test_explicit_selection_rejects_wrong_identity_validation_and_no_pickup(self):
        base = {'dataSHA256': mask.sha(self.teacher / 'data.bin'),
                'reportSHA256': mask.sha(self.teacher / 'report.json'), 'episodes': []}
        item0 = teacher_identity(self.teacher, 0)
        wrong = [[], [dict(item0, seed=101)], [teacher_identity(self.teacher, 2)],
                 [item0, item0], [teacher_identity(self.teacher, 1)]]
        for index, episodes in enumerate(wrong):
            selection = {str(self.teacher.absolute()): dict(base, episodes=episodes)}
            output = self.root / ('bad-selection-' + str(index))
            with self.subTest(episodes=episodes), self.assertRaises(ValueError):
                mask.create(self.data, self.inputs, output, self.map, min_free=0, teacher_selection=selection)
            self.assertFalse(output.exists())
        selection = {str(self.teacher.absolute()): dict(base, dataSHA256='0' * 64,
                                                        episodes=[item0])}
        with self.assertRaisesRegex(ValueError, 'identity differs'):
            mask.create(self.data, self.inputs, self.root / 'wrong-sha', self.map, min_free=0, teacher_selection=selection)
        with self.assertRaisesRegex(ValueError, 'bind every teacher shard'):
            mask.create(self.data, self.inputs, self.root / 'missing-source', self.map, min_free=0, teacher_selection={})
        with self.assertRaisesRegex(ValueError, 'duplicate source shard'):
            mask.create(self.data, self.inputs + [(self.teacher, True)], self.root / 'duplicate', self.map, min_free=0, teacher_selection=selection)

    def test_selection_rejects_changed_episode_evidence(self):
        chosen = {str(self.teacher.absolute()): {
            'dataSHA256': mask.sha(self.teacher / 'data.bin'),
            'reportSHA256': mask.sha(self.teacher / 'report.json'),
            'episodes': [teacher_identity(self.teacher, 0)]}}
        for name in ('result.json', 'initial.json', 'chase.jsonl', 'decisions.jsonl'):
            path = self.teacher / 'expert-0' / name; original = path.read_bytes()
            path.write_bytes(original + b'\n')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'episode evidence changed'):
                mask.create(self.data, self.inputs, self.root / ('changed-' + name), self.map,
                            min_free=0, teacher_selection=chosen)
            path.write_bytes(original)


class RealFormatTest(unittest.TestCase):
    def test_300_action_cutoff_keeps_action_that_caused_consumption(self):
        with tempfile.TemporaryDirectory() as name:
            root = pathlib.Path(name)
            teacher = write_shard(root, 'teacher', [150, 300], 1, True)
            data, _ = aggregate(root, [teacher])
            result = mask.create(data, [(teacher, True)], root / 'derived', min_free=0)
            self.assertEqual(result['episodes'][0]['firstConsumptionAction'], 150)
            with (root / 'derived/data.bin').open('rb') as stream:
                offset = 32 + mask.HORIZON * mask.IMAGE
                stream.seek(offset + 149 * mask.AGG_ROW + 40); self.assertEqual(stream.read(4), mask.ONE)
                stream.seek(offset + 150 * mask.AGG_ROW + 40); self.assertEqual(stream.read(4), mask.ZERO)
                stream.seek(offset + 150 * mask.AGG_ROW + 44); self.assertEqual(stream.read(4), mask.ONE)

    def test_fitting_selection_in_native_format_preserves_other_validation(self):
        with tempfile.TemporaryDirectory() as name:
            root = pathlib.Path(name)
            teacher = write_shard(root, 'teacher', [150, 180, 90], 2, True)
            student = write_shard(root, 'student', [None, None], 1, False)
            data, maps = aggregate(root, [teacher, student])
            chosen = {str(teacher.absolute()): {'dataSHA256': mask.sha(teacher / 'data.bin'),
                       'reportSHA256': mask.sha(teacher / 'report.json'),
                       'episodes': [teacher_identity(teacher, 0)]}}
            result = mask.create(data, [(teacher, True), (student, False)], root / 'selected', maps,
                                 min_free=0, teacher_selection=chosen)
            self.assertEqual((result['outputEpisodes'], result['outputFittingEpisodes']), (3, 2))
            self.assertEqual([(row['episode'], row['fit']) for row in result['excludedTeacherEpisodes']], [(1, True), (2, False)])
            self.assertEqual(result['fittingTeacherLabels'], 150)
            with (root / 'selected/data.bin').open('rb') as stream:
                stream.seek(32 + mask.HORIZON * mask.IMAGE + 150 * mask.AGG_ROW + 40)
                self.assertEqual(stream.read(8), mask.ZERO + mask.ONE)


if __name__ == '__main__':
    unittest.main()

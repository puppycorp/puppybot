#!/usr/bin/env python3
"""Compare the actual floor guard with independent rectangle/cell geometry."""
import math
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARCHIVE = ROOT / 'build/flex/sim/levels-v2/pitch82/dock-clearance-build-v1'
COMPILER = ROOT / 'build/flex/control/compiler'


def function(text, name):
    start = text.index('fn ' + name + '(')
    end = text.index('\nfn ', start + 1)
    return text[start:end]


def intersects(x, y, angle, column, row):
    """Separating axes for a rotated robot rectangle and a grid square."""
    c, s = math.cos(angle), math.sin(angle)
    dx, dy = (column + 0.5) / 10 - 10 - x, (row + 0.5) / 10 - 10 - y
    tolerance = 1e-9
    return (abs(dx) <= .05 + .15 * abs(c) + .12 * abs(s) + tolerance and
            abs(dy) <= .05 + .15 * abs(s) + .12 * abs(c) + tolerance and
            abs(c * dx + s * dy) <= .15 + .05 * (abs(c) + abs(s)) + tolerance and
            abs(c * dy - s * dx) <= .12 + .05 * (abs(c) + abs(s)) + tolerance)


class ObservedFootprintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='puppy-footprint-')
        temp = Path(cls.tmp.name)
        source = temp / 'source'; build = temp / 'build'
        shutil.copytree(ARCHIVE / 'source', source)
        shutil.copytree(ARCHIVE / 'build', build)
        library = build / 'flex/sim/library'; adapter = library / 'lib/f64.flex'
        old = f'import "{ARCHIVE / "source/core/words.flex"}";'
        new = f'import "{source / "core/words.flex"}";'
        text = adapter.read_text()
        if text.count(old) != 1:
            raise ValueError('unexpected library source')
        adapter.write_text(text.replace(old, new, 1))
        (library.parent / 'dependencies.flex').write_text(
            f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
        main = source / 'sim/main.flex'; text = main.read_text()
        if text.count('fn main(argc, argv) {') != 1:
            raise ValueError('unexpected simulator entry point')
        nav = source / 'sim/navigation.flex'; original = nav.read_text()
        baseline = function(original, 'ps_nav_observed_clear')
        current = function((ROOT / 'flex/sim/navigation.flex').read_text(), 'ps_nav_observed_clear')
        nav.write_text(original.replace(baseline, current, 1))
        subprocess.run([str(COMPILER), str(main), '-o', str(temp / 'simulator')], cwd=ROOT,
                       capture_output=True, text=True, timeout=120, check=True)
        main.write_text(text.replace('fn main(argc, argv) {', 'fn footprint_original_main(argc, argv) {', 1)
                        + '\n' + (HERE / 'probe.flex').read_text())
        cls.results = []
        for index, body in enumerate((baseline, current)):
            nav.write_text(original.replace(baseline, body, 1))
            executable = temp / f'probe-{index}'
            subprocess.run([str(COMPILER), str(main), '-o', str(executable)], cwd=ROOT,
                           capture_output=True, text=True, timeout=120, check=True)
            result = subprocess.run([str(executable)] + (['current'] if index else []), cwd=ROOT, capture_output=True,
                                    text=True, timeout=60, check=True)
            cls.results.append(result.stdout.splitlines())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_full_coarse_footprint(self):
        expected = []
        for degrees in range(0, 360, 5):
            for px in range(0, 81, 20):
                for py in range(0, 81, 20):
                    for row in range(98, 103):
                        for column in range(98, 103):
                            expected.append('0' if intersects(px / 1000, py / 1000,
                                                            math.radians(degrees), column, row) else '1')
        self.assertEqual(len(expected), 45000)
        old, current = self.results[0][0], self.results[1][0]
        self.assertEqual(current, ''.join(expected))
        misses = sum(a == '1' and b == '0' for a, b in zip(old, expected))
        self.assertGreater(misses, 0)
        print(f'Old guard missed {misses} blocked-cell overlaps; corrected guard matched {len(expected)} geometry checks.')

    def test_detail_fallback_and_bounds(self):
        # Overlapping coarse cell without detail, then with observed-clear
        # detail, an overlapping blocked detail cell, an unrelated detail
        # cell and OOB.
        # With coarse floor clear, blocked/unknown detail remains ignored.
        self.assertEqual(self.results[0][1][0], '1')
        self.assertEqual(self.results[1][1], '010101')

    def test_nonfinite_poses_rejected(self):
        self.assertEqual(self.results[1][2], '0000')


if __name__ == '__main__':
    unittest.main()

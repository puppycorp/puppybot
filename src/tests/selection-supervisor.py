#!/usr/bin/env python3
"""CPU-only tests for the diagnostic selection process monitor."""
import contextlib
import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'datasets/visual-control/chase-v1/levels/supervise-selection.py'
spec = importlib.util.spec_from_file_location('selection_supervisor', TOOL)
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)

PROGRAM = r'''
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <unistd.h>
int main(int argc, char **argv) {
    if (argc < 2) return 2;
    int fd = open(argv[1], O_RDONLY);
    if (fd < 0) return 3;
    void *p = mmap(0, 4096, PROT_READ, MAP_PRIVATE, fd, 0);
    if (p == MAP_FAILED) return 4;
    volatile char byte = *(char *)p;
    if (argc > 3 && strcmp(argv[2], "escape") == 0) {
        pid_t child = fork();
        if (child < 0) return 6;
        if (child == 0) { setsid(); signal(SIGTERM, SIG_IGN); sleep(30); return 0; }
        FILE *f = fopen(argv[3], "w"); if (!f) return 7;
        fprintf(f, "%d\n", (int)child); fclose(f); sleep(30); return 0;
    }
    usleep(600000);
    return byte == 0 ? 5 : 0;
}
'''


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='selection-supervisor-test-')
        self.root = Path(self.tmp.name)
        self.hip = self.root / 'expected' / 'libamdhip64.so'
        self.hip.parent.mkdir()
        self.hip.write_bytes(b'a' * 4096)
        self.other = self.root / 'other' / 'libamdhip64.so'
        self.other.parent.mkdir()
        self.other.write_bytes(b'b' * 4096)
        source = self.root / 'policy.c'
        source.write_text(PROGRAM)
        self.policy = self.root / 'policy'
        subprocess.run(['cc', str(source), '-o', str(self.policy)], check=True, capture_output=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_monitor(self, name, mapped):
        output = self.root / name
        argv = [str(TOOL), str(output), '--', str(self.policy), str(mapped), 'marker']
        with mock.patch.object(monitor, 'HIP', self.hip), mock.patch.object(sys, 'argv', argv), \
                mock.patch.dict(os.environ, {'AWS_SECRET_ACCESS_KEY': 'DO_NOT_RECORD_THIS'}), \
                contextlib.redirect_stdout(io.StringIO()):
            code = monitor.main()
        lines = [json.loads(line) for line in (output / 'observations.jsonl').read_text().splitlines()]
        self.assertNotIn('DO_NOT_RECORD_THIS', (output / 'observations.jsonl').read_text())
        return code, lines

    def test_observes_exact_argv_starttime_and_expected_mapping_without_certification(self):
        code, events = self.run_monitor('good', self.hip)
        self.assertEqual(code, 2)  # diagnostic, never an attestation pass
        processes = [event for event in events if event['event'] == 'process' and event['executable'] == str(self.policy)]
        self.assertTrue(processes)
        self.assertEqual(processes[0]['argv'], [str(self.policy), str(self.hip), 'marker'])
        self.assertGreater(processes[0]['starttime'], 0)
        self.assertEqual(processes[0]['executableSHA256'], monitor.sha(self.policy))
        self.assertEqual(events[-1]['observedPolicies'], 1)
        self.assertEqual(events[-1]['policiesWithExpectedHipFileMapping'], 1)
        self.assertEqual(events[-1]['status'], 'diagnostic_only')
        self.assertFalse(events[-1]['eligibleForQualification'])

    def test_unexpected_hip_mapping_fails_closed(self):
        code, events = self.run_monitor('wrong', self.other)
        self.assertEqual(code, 1)
        self.assertTrue(any('unexpected HIP mapping' in e.get('message', '') for e in events))
        self.assertFalse(events[-1]['eligibleForQualification'])

    def test_executable_path_race_is_not_recorded_as_a_valid_observation(self):
        original = os.readlink
        calls = []
        def stale_first_exe(path):
            if str(path) == f'/proc/{os.getpid()}/exe':
                calls.append(1)
                if len(calls) == 1:
                    return '/stale/previous-executable'
            return original(path)
        with mock.patch.object(monitor.os, 'readlink', side_effect=stale_first_exe):
            with self.assertRaises(monitor.ProcessRace):
                monitor.observe(os.getpid(), ((0, 0), 0), {})

    def test_existing_output_is_not_overwritten(self):
        output = self.root / 'existing'
        output.mkdir()
        (output / 'keep').write_text('preserved')
        argv = [str(TOOL), str(output), '--', str(self.policy), str(self.hip)]
        with mock.patch.object(monitor, 'HIP', self.hip), mock.patch.object(sys, 'argv', argv):
            with self.assertRaisesRegex(ValueError, 'already exists'):
                monitor.main()
        self.assertEqual((output / 'keep').read_text(), 'preserved')

    def test_interruption_cleans_escaped_adopted_child(self):
        output, pidfile = self.root / 'interrupted', self.root / 'child.pid'
        argv = [str(TOOL), str(output), '--', str(self.policy), str(self.hip), 'escape', str(pidfile)]
        timer = threading.Timer(0.8, lambda: os.kill(os.getpid(), signal.SIGTERM))
        repeat = threading.Timer(1.2, lambda: os.kill(os.getpid(), signal.SIGTERM))
        start = time.monotonic()
        with mock.patch.object(monitor, 'HIP', self.hip), mock.patch.object(sys, 'argv', argv), \
                contextlib.redirect_stdout(io.StringIO()):
            timer.start()
            repeat.start()
            try:
                code = monitor.main()
            finally:
                timer.cancel()
                repeat.cancel()
        self.assertEqual(code, 1)
        self.assertLess(time.monotonic() - start, 8)
        self.assertTrue(pidfile.exists())
        child = int(pidfile.read_text())
        self.assertFalse(Path(f'/proc/{child}').exists(), f'escaped child {child} survived')
        result = json.loads((output / 'observations.jsonl').read_text().splitlines()[-1])
        self.assertTrue(any('received signal' in error for error in result['errors']))
        self.assertFalse(result['eligibleForQualification'])

    def test_signal_immediately_after_spawn_does_not_leave_runner(self):
        output = self.root / 'spawn-signal'
        argv = [str(TOOL), str(output), '--', str(self.policy), str(self.hip)]
        original = subprocess.Popen
        spawned = []
        def start_and_interrupt(*args, **kwargs):
            child = original(*args, **kwargs)
            spawned.append(child.pid)
            os.kill(os.getpid(), signal.SIGTERM)
            return child
        with mock.patch.object(monitor, 'HIP', self.hip), mock.patch.object(sys, 'argv', argv), \
                mock.patch.object(monitor.subprocess, 'Popen', side_effect=start_and_interrupt), \
                contextlib.redirect_stdout(io.StringIO()):
            code = monitor.main()
        self.assertEqual(code, 1)
        self.assertEqual(len(spawned), 1)
        self.assertFalse(Path(f'/proc/{spawned[0]}').exists(), 'runner survived spawn-window interruption')
        result = json.loads((output / 'observations.jsonl').read_text().splitlines()[-1])
        self.assertTrue(any('received signal' in error for error in result['errors']))
        self.assertFalse(result['eligibleForQualification'])

    def test_signal_after_short_lived_runner_is_reported(self):
        output = self.root / 'short-signal'
        argv = [str(TOOL), str(output), '--', '/usr/bin/true']
        original = subprocess.Popen
        def finish_and_interrupt(*args, **kwargs):
            child = original(*args, **kwargs)
            child.wait()
            os.kill(os.getpid(), signal.SIGTERM)
            return child
        with mock.patch.object(monitor, 'HIP', self.hip), mock.patch.object(sys, 'argv', argv), \
                mock.patch.object(monitor.subprocess, 'Popen', side_effect=finish_and_interrupt), \
                contextlib.redirect_stdout(io.StringIO()):
            code = monitor.main()
        self.assertEqual(code, 1)
        result = json.loads((output / 'observations.jsonl').read_text().splitlines()[-1])
        self.assertTrue(any('received signal' in error for error in result['errors']))
        self.assertFalse(result['eligibleForQualification'])


if __name__ == '__main__':
    unittest.main()

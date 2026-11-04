#!/usr/bin/env python3
"""Small synthetic checks of the aggregate supervisor and advisory lock."""
import fcntl
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('aggregate_supervisor_test', HERE/'supervise.py')
s = importlib.util.module_from_spec(spec); spec.loader.exec_module(s)


class SupervisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='aggregate-supervisor-',dir=ROOT/'build')
        self.root = Path(self.tmp.name)
        self.monitor = self.root/'monitor'; self.output = self.root/'output'; self.lock = self.root/'lock'
        self.lock.touch()
        self.patches = [mock.patch.object(s,'MONITOR',self.monitor), mock.patch.object(s,'LOCK',self.lock),
                        mock.patch.object(s.builder,'OUTPUT',self.output),
                        mock.patch.object(s.base.guard,'require_dedicated_process'),
                        mock.patch.object(s.base,'low_priority',return_value={'cpuNice':15,'ioClass':'idle'}),
                        mock.patch.object(s,'pins',return_value={'source':'hash'}),
                        mock.patch.object(s.shutil,'disk_usage',return_value=shutil._ntuple_diskusage(200*s.GIB,0,200*s.GIB))]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def test_supervisor_uses_fresh_lock_and_checks_both_workers(self):
        calls=[]
        status={'clientExit':0,'signal':None,'timedOut':False,'remainingWorkersTerminated':False,'processGroup':123}
        def fake_supervise(command,directory,env,seconds):
            calls.append((command,Path(directory),seconds))
            directory=Path(directory)
            (directory/'supervisor-result.json').write_text(json.dumps(status))
            if directory == self.monitor:
                self.output.mkdir(); report={'status':'candidate_data_only','trainingAuthorized':False,
                    'dataSHA256':'d','mapSHA256':'m','verification':{'episodes':6}}
                (self.output/'report.json').write_text(json.dumps(report))
                worker={'status':'candidate_data_only','reportSHA256':s.base.sha(self.output/'report.json'),
                    'dataSHA256':'d','mapSHA256':'m','sourcePins':{'source':'hash'},'cpuNice':15,'ioClass':'idle'}
                (self.monitor/'worker-result.json').write_text(json.dumps(worker))
            else:
                final={'status':'candidate_bytes_verified','reportSHA256':s.base.sha(self.output/'report.json'),
                       'verification':{'episodes':6},'cpuNice':15,'ioClass':'idle'}
                (self.monitor/'final-result.json').write_text(json.dumps(final))
            return status
        with mock.patch.object(s.base.hidden,'supervise',side_effect=fake_supervise):
            report=s.launch()
        self.assertEqual(report['status'],'candidate_data_only')
        self.assertEqual(len(calls),2)
        self.assertIn('m.worker()',calls[0][0][-2]); self.assertIn('m.final_worker()',calls[1][0][-2])
        receipt=json.loads((self.monitor/'result.json').read_text())
        self.assertEqual(receipt['status'],'candidate_data_only')
        self.assertIsNotNone(receipt['finalResultSHA256']); self.assertIsNotNone(receipt['finalStatusSHA256'])

    def test_already_held_lock_refuses_before_output(self):
        with self.lock.open('r+') as held:
            fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError): s.launch()
        self.assertFalse(self.monitor.exists());self.assertFalse(self.output.exists())

    def test_unshared_full_size_reserve_required(self):
        with mock.patch.object(s.shutil,'disk_usage',return_value=shutil._ntuple_diskusage(40*s.GIB,0,40*s.GIB)):
            with self.assertRaises(ValueError): s.launch()
        self.assertFalse(self.monitor.exists());self.assertFalse(self.output.exists())


if __name__=='__main__': unittest.main()

#!/usr/bin/env python3
"""CPU-only supervisor fixtures; never invokes the real build or GPU."""
import fcntl
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('build_supervisor_fixture',HERE/'supervisor.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class BuildSupervisorTest(unittest.TestCase):
    def test_cli_disabled_and_priority_command(self):
        result=subprocess.run([sys.executable,'-I',str(HERE/'supervisor.py')],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('disabled',result.stderr.lower())
        command=m.command();self.assertEqual(command[:5],[str(m.NICE),'-n','15',str(m.IONICE),'-c']);self.assertEqual(command[5],'3')
        code='import os,subprocess;print(os.getpriority(os.PRIO_PROCESS,0));print(subprocess.check_output(["/usr/bin/ionice","-p",str(os.getpid())],text=True).strip())'
        p=subprocess.run([str(m.NICE),'-n','15',str(m.IONICE),'-c','3',sys.executable,'-I','-c',code],capture_output=True,text=True,timeout=5,check=True)
        cpu,io=p.stdout.splitlines();self.assertGreaterEqual(int(cpu),15);self.assertEqual(io,'idle')
        supervisor_code=('import importlib.util,json,sys;'
                         's=importlib.util.spec_from_file_location("m",sys.argv[1]);'
                         'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);print(json.dumps(m.low_priority()))')
        result=subprocess.run([sys.executable,'-I','-c',supervisor_code,str(HERE/'supervisor.py')],capture_output=True,text=True,timeout=5,check=True)
        priority=json.loads(result.stdout);self.assertGreaterEqual(priority['cpuNice'],15);self.assertEqual(priority['ioClass'],'idle')

    def test_disk_paths_and_no_overwrite(self):
        for mode in ('workspace','home','output','existing-build','existing-monitor'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);build=root/'build';monitor=root/'monitor';lock=root/'lock';lock.touch()
                if mode=='existing-build':build.mkdir();(build/'sentinel').write_text('keep')
                if mode=='existing-monitor':monitor.mkdir();(monitor/'sentinel').write_text('keep')
                def disk(path):
                    points={str(root/'workspace'):'workspace',str(root/'home'):'home',str(root):'output'}
                    return type('D',(),{'free':(33 if points[str(path)]==mode else 40)*m.GIB})()
                with mock.patch.object(m.guard,'require_dedicated_process'),mock.patch.object(m,'low_priority',return_value={'cpuNice':15,'ioClass':'idle'}),mock.patch.object(m,'ROOT',root/'workspace'),mock.patch.object(m,'P',root),mock.patch.object(m,'BUILD',build),mock.patch.object(m,'MONITOR',monitor),mock.patch.object(m,'LOCK',lock),mock.patch.object(m.Path,'home',return_value=root/'home'),mock.patch.object(m.shutil,'disk_usage',side_effect=disk):
                    with self.assertRaises((ValueError,FileExistsError)):m.launch()
                if mode.startswith('existing-'):self.assertEqual(((build if mode=='existing-build' else monitor)/'sentinel').read_text(),'keep')
                else:self.assertFalse(build.exists() or monitor.exists())

    def test_lock_contention_leaves_no_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);lock=root/'lock';lock.touch()
            with lock.open('r+') as held:
                fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with mock.patch.object(m.guard,'require_dedicated_process'),mock.patch.object(m,'low_priority',return_value={'cpuNice':15,'ioClass':'idle'}),mock.patch.object(m,'P',root),mock.patch.object(m,'BUILD',root/'build'),mock.patch.object(m,'MONITOR',root/'monitor'),mock.patch.object(m,'LOCK',lock),mock.patch.object(m.shutil,'disk_usage',return_value=type('D',(),{'free':40*m.GIB})()):
                    with self.assertRaises(BlockingIOError):m.launch()
            self.assertFalse((root/'build').exists() or (root/'monitor').exists())

    def test_build_receipt_failure_and_source_binding(self):
        clean={'clientExit':0,'timedOut':False,'signal':None,'remainingWorkersTerminated':False,'processGroup':123}
        for mode in ('ok','missing-signal','status-mismatch','source-change','bad-priority','bad-binary','low-final','spawn-error'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);build=root/'build';monitor=root/'monitor';lock=root/'lock';lock.touch();pins={'synthetic-source':'source-sha'}
                def supervise(command,directory,env,seconds):
                    if mode=='spawn-error':raise OSError('spawn failed')
                    build.mkdir();(build/'client').write_bytes(b'client');(build/'simulator').write_bytes(b'simulator')
                    ch=m.sha(build/'client');sh=m.sha(build/'simulator');report={'schema':'puppybot.physical-search-fallback-build.v1','clientSHA256':ch,'simulatorSHA256':sh}
                    (build/'build.json').write_text(json.dumps(report));worker={'status':'isolated_build_only','sourcePins':pins,'cpuNice':0 if mode=='bad-priority' else 15,'ioClass':'idle','clientSHA256':'incorrect' if mode=='bad-binary' else ch,'simulatorSHA256':sh,'buildReceiptSHA256':m.sha(build/'build.json')}
                    (directory/'worker-result.json').write_text(json.dumps(worker));(directory/'supervisor-result.json').write_text(json.dumps(dict(clean,processGroup=321) if mode=='status-mismatch' else clean))
                    return {k:v for k,v in clean.items() if k!='signal'} if mode=='missing-signal' else clean
                calls=0
                def disk(path):
                    nonlocal calls
                    calls+=1;return type('D',(),{'free':(31 if mode=='low-final' and calls>6 else 40)*m.GIB})()
                def source():
                    nonlocal seen
                    seen+=1;return {'synthetic-source':'changed'} if mode=='source-change' and seen>1 else pins
                seen=0
                with mock.patch.object(m.guard,'require_dedicated_process'),mock.patch.object(m,'low_priority',return_value={'cpuNice':15,'ioClass':'idle'}),mock.patch.object(m,'P',root),mock.patch.object(m,'BUILD',build),mock.patch.object(m,'MONITOR',monitor),mock.patch.object(m,'LOCK',lock),mock.patch.object(m,'sources',side_effect=source),mock.patch.object(m.shutil,'disk_usage',side_effect=disk),mock.patch.object(m.hidden,'supervise',side_effect=supervise):
                    if mode=='spawn-error':
                        with self.assertRaisesRegex(OSError,'spawn failed'):m.launch()
                    else:self.assertEqual(m.launch(),0 if mode=='ok' else 1)
                result=json.loads((monitor/'result.json').read_text());self.assertEqual(result['status'],'isolated_build_only' if mode=='ok' else 'failed')
                self.assertEqual((monitor/'launch.json').exists(),True)

    def test_source_walk_failure_is_not_silenced(self):
        def bad(root,followlinks,onerror):
            onerror(PermissionError('unreadable archive'))
            yield None
        with mock.patch.object(m.os,'walk',side_effect=bad):
            with self.assertRaisesRegex(PermissionError,'unreadable'):m.sources()

    def test_worker_is_bounded_and_uses_mock_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);build=root/'build';monitor=root/'monitor';monitor.mkdir()
            def build_stub(path):
                path.mkdir();(path/'build.json').write_text('{}');(path/'client').write_text('client');(path/'simulator').write_text('sim')
                return {'schema':'synthetic'}
            prepare=type('Prepare',(),{'build':staticmethod(build_stub)})
            trial=type('Trial',(),{'check_build':staticmethod(lambda p:{'schema':'synthetic'})})
            def loader(name,path):return prepare if name=='worker_search_prepare' else trial
            with mock.patch.object(m,'BUILD',build),mock.patch.object(m,'MONITOR',monitor),mock.patch.object(m,'sources',return_value={'input':'hash'}),mock.patch.object(m,'load',side_effect=loader),mock.patch.object(m.os,'getpriority',return_value=15),mock.patch.object(m.subprocess,'run',return_value=type('R',(),{'stdout':'idle\n'})()):m.worker()
            self.assertEqual(json.loads((monitor/'worker-result.json').read_text())['status'],'isolated_build_only')

    def test_real_watchdog_cleans_escaped_child_and_repeated_signal(self):
        grandchild='import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)'
        child=('import os,signal,subprocess,sys,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);'
               'p=subprocess.Popen([sys.executable,"-c",sys.argv[2]],start_new_session=True);'
               'open(sys.argv[1],"w").write(str(os.getpid())+" "+str(p.pid));time.sleep(30)')
        outer=textwrap.dedent('''
            import importlib.util,json,os,sys
            from pathlib import Path
            s=importlib.util.spec_from_file_location('m',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
            status=m.hidden.supervise([sys.executable,'-c',sys.argv[4],sys.argv[3],sys.argv[5]],Path(sys.argv[2]),os.environ.copy(),.5 if sys.argv[6]=='timeout' else 20)
            print(json.dumps(status))
        ''')
        sibling=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
        try:
            for mode in ('timeout','signal'):
                with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                    pidfile=Path(tmp)/'workers.pid';args=[sys.executable,'-c',outer,str(HERE/'supervisor.py'),tmp,str(pidfile),child,grandchild,mode]
                    if mode=='timeout':
                        result=subprocess.run(args,capture_output=True,text=True,timeout=20,check=True);status=json.loads(result.stdout);self.assertTrue(status['timedOut'])
                    else:
                        process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);deadline=time.monotonic()+5
                        while not pidfile.exists() and time.monotonic()<deadline:time.sleep(.01)
                        self.assertTrue(pidfile.exists());grand=int(pidfile.read_text().split()[1]);os.kill(process.pid,signal.SIGTERM)
                        deadline=time.monotonic()+8;adopted=False
                        while time.monotonic()<deadline:
                            try:
                                lines=Path(f'/proc/{grand}/status').read_text().splitlines();parent=int(next(x.split()[1] for x in lines if x.startswith('PPid:')))
                                if parent==process.pid:adopted=True;break
                            except (FileNotFoundError,StopIteration):pass
                            time.sleep(.002)
                        self.assertTrue(adopted);os.kill(process.pid,signal.SIGTERM);stdout,stderr=process.communicate(timeout=20)
                        self.assertEqual(process.returncode,0,stderr);status=json.loads(stdout);self.assertEqual(status['signal'],signal.SIGTERM)
                    self.assertFalse(m.clean(status));self.assertIsNone(sibling.poll())
                    for pid in map(int,pidfile.read_text().split()):self.assertFalse(Path(f'/proc/{pid}').exists())
        finally:sibling.terminate();sibling.wait(timeout=5)


if __name__=='__main__':unittest.main()

#!/usr/bin/env python3
"""CPU-only synthetic reservation and isolated native-dispatch fixtures."""
import hashlib
import importlib.util
import json
import os
import select
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('guard_prepare',HERE/'prepare.py')
prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)


def sha(data):return hashlib.sha256(data).hexdigest()


class NativeGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='puppy-scene-guard-');cls.root=Path(cls.temp.name)
        cls.build=cls.root/'build-copy';cls.receipt=prepare.prepare(cls.build);cls.binary=cls.build/'control-guarded'
        cls.home=cls.root/'runtime';sim=cls.home/'build/flex/control/simulator';sim.parent.mkdir(parents=True)
        sim.write_text('#!/usr/bin/python3\nimport os\nfrom pathlib import Path\nPath(os.environ["GUARD_SENTINEL"]).write_text("started")\n');sim.chmod(0o755)
        cls.model=cls.root/'model';cls.model.mkdir();(cls.model/'kernels').mkdir();(cls.model/'weights.bin').write_bytes(b'weights')
        policy=cls.model/'policy';policy.write_text('#!/usr/bin/python3\nimport os\nos.write(3,b"VCPOL001")\ntry:\n while os.read(3,1):pass\nexcept OSError:pass\n');policy.chmod(0o755)
        kernels={}
        for i in range(5):
            item=cls.model/'kernels'/str(i);item.write_text('kernel'+str(i));kernels[item.name]=prepare.sha(item)
        (cls.model/'receipt.json').write_text(json.dumps({'weightsSHA256':prepare.sha(cls.model/'weights.bin'),'binarySHA256':prepare.sha(policy),'memoryWidth':128,'kernels':kernels}))
        cls.case=b'{"id":"synthetic fitting"}';cls.environment=b'synthetic fitting environment'
        cls.reserved_case=b'{"id":"synthetic reserved"}';cls.reserved_environment=b'synthetic reserved environment'
        cls.layout=json.dumps({'fit':True,'startRoom':0,'rooms':[[-2,-2,2,2]]}).encode()
        rows=[]
        for level in range(1,6):
            for i in range(32):
                layout=226+i if level<4 else 227+2*i
                rows.append({'level':level,'index':i,'seed':1700000000+level*100+i,'layoutId':layout,
                             'scene':f'generated/{layout}/{i%16}','caseSHA256':sha(cls.reserved_case),'environmentSHA256':sha(cls.reserved_environment)})
        cls.manifest=cls.root/'synthetic-reservations.json'
        cls.manifest.write_text(json.dumps({'status':'reserved_not_evaluated','task':'virtual-fetch','gamesPerLevel':32,'rows':rows}))
        cls.fixture_index=0

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def setUp(self):
        type(self).fixture_index+=1;self.work=self.root/f'fixture-{type(self).fixture_index}';self.work.mkdir()
        self.scene=self.work/'scene';self.scene.mkdir();(self.scene/'case.json').write_bytes(self.case)
        (self.scene/'environment.bin').write_bytes(self.environment);(self.scene/'layout.json').write_bytes(self.layout)
        self.sentinel=self.work/'simulator-started';self.output=self.work/'output'

    def environment_vars(self):
        return dict(os.environ,PUPPYBOT_RESERVED_MANIFEST=str(self.manifest),PUPPYBOT_RESERVED_MANIFEST_SHA256=prepare.sha(self.manifest),GUARD_SENTINEL=str(self.sentinel))

    def command(self,kind='run',scene=None,catalog=False,binary=None):
        command=[str(binary or self.binary),kind,'--output',str(self.output),'--horizon','2']
        command+=['--scene-catalog' if catalog else '--scene',str(scene or self.scene)]
        if kind=='run':command+=['--chase-forward','--fetch','--episodes','1']
        elif kind=='collect':command+=['--chase','--fetch','--episodes','2','--validation','1']
        else:command+=['--policy',str(self.model),'--episodes','2','--validation','1','--rollin','1']
        return command

    def run_control(self,kind='run',scene=None,catalog=False,env=None,binary=None):
        return subprocess.run(self.command(kind,scene,catalog,binary),cwd=self.home,env=env or self.environment_vars(),capture_output=True,text=True,timeout=15)

    def test_synthetic_fit_scene_copies_private_bytes_and_reaches_stub(self):
        result=self.run_control();self.assertNotEqual(result.returncode,0)
        self.assertTrue(self.sentinel.exists(),result.stderr)
        world=self.output/'110000/scene'
        self.assertEqual((world/'case.json').read_bytes(),self.case);self.assertEqual((world/'environment.bin').read_bytes(),self.environment)
        self.assertEqual((world/'layout.json').read_bytes(),self.layout)
        self.assertNotIn('guard:',result.stderr)

    def test_all_native_dispatches_reject_reserved_content(self):
        for kind in ('run','collect','correct'):
            with self.subTest(kind=kind):
                self.setUp();(self.scene/'case.json').write_bytes(self.reserved_case)
                result=self.run_control(kind);self.assertNotEqual(result.returncode,0)
                self.assertIn('guard: exact reserved scene content',result.stderr);self.assertFalse(self.sentinel.exists())

    def test_role_missing_metadata_and_stripped_role_hashes_reject(self):
        variants=[('role',{'fit':True,'reservedHeldOut':True,'rooms':[[-2,-2,2,2]],'startRoom':0},None,None),
                  ('not_fit',{'fit':False,'rooms':[[-2,-2,2,2]],'startRoom':0},None,None),
                  ('malformed',{'fit':'true','rooms':[[-2,-2,2,2]],'startRoom':0},None,None),
                  ('reserved-case',None,self.reserved_case,None),('reserved-env',None,None,self.reserved_environment)]
        for name,metadata,case,environment in variants:
            with self.subTest(name=name):
                self.setUp()
                if metadata is not None:(self.scene/'layout.json').write_text(json.dumps(metadata))
                if case is not None:(self.scene/'case.json').write_bytes(case)
                if environment is not None:(self.scene/'environment.bin').write_bytes(environment)
                result=self.run_control();self.assertNotEqual(result.returncode,0);self.assertIn('guard:',result.stderr);self.assertFalse(self.sentinel.exists())
        self.setUp();(self.scene/'layout.json').unlink();result=self.run_control();self.assertNotEqual(result.returncode,0);self.assertFalse(self.sentinel.exists())
        for name in ('case.json','environment.bin'):
            with self.subTest(missing=name):
                self.setUp();(self.scene/name).unlink();result=self.run_control();self.assertNotEqual(result.returncode,0);self.assertFalse(self.sentinel.exists())

    def test_manifest_pin_missing_changed_and_duplicate_fail(self):
        for mode in ('missing','wrong','duplicate','bad_mapping'):
            with self.subTest(mode=mode):
                self.setUp();env=self.environment_vars()
                if mode=='missing':env.pop('PUPPYBOT_RESERVED_MANIFEST_SHA256')
                elif mode=='wrong':env['PUPPYBOT_RESERVED_MANIFEST_SHA256']='0'*64
                else:
                    bad=self.work/'bad-manifest.json';manifest=json.loads(self.manifest.read_text());manifest['rows'][1]=manifest['rows'][0];bad.write_text(json.dumps(manifest))
                    if mode=='bad_mapping':
                        manifest=json.loads(self.manifest.read_text());manifest['rows'][0]['seed']+=1;bad.write_text(json.dumps(manifest))
                    env['PUPPYBOT_RESERVED_MANIFEST']=str(bad);env['PUPPYBOT_RESERVED_MANIFEST_SHA256']=prepare.sha(bad)
                result=self.run_control(env=env);self.assertNotEqual(result.returncode,0);self.assertIn('guard:',result.stderr);self.assertFalse(self.sentinel.exists())

    def test_implicit_generated_scene_is_rejected(self):
        command=self.command();index=command.index('--scene');del command[index:index+2]
        result=subprocess.run(command,cwd=self.home,env=self.environment_vars(),capture_output=True,text=True,timeout=15)
        self.assertNotEqual(result.returncode,0);self.assertIn('guard: explicit scene',result.stderr);self.assertFalse(self.sentinel.exists())

    def test_symlink_catalog_and_file_targets_checked(self):
        catalog=self.work/'catalog';catalog.mkdir();(catalog/'0').symlink_to(self.scene,target_is_directory=True)
        (self.scene/'case.json').unlink();reserved=self.work/'reserved';reserved.write_bytes(self.reserved_case)
        (self.scene/'case.json').symlink_to(reserved)
        result=self.run_control(scene=catalog,catalog=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('guard: exact reserved scene content',result.stderr);self.assertFalse(self.sentinel.exists())

    def test_old_baseline_can_reach_synthetic_reserved_scene(self):
        (self.scene/'case.json').write_bytes(self.reserved_case)
        (self.scene/'layout.json').write_text(json.dumps({'fit':False,'reservedHeldOut':True,'startRoom':0,'rooms':[[-2,-2,2,2]]}))
        result=self.run_control(binary=self.build/'baseline')
        self.assertNotEqual(result.returncode,0);self.assertTrue(self.sentinel.exists(),result.stderr)

    def test_source_symlink_swap_after_snapshot_cannot_change_copied_bytes(self):
        race=self.work/'race-source';shutil.copytree(self.build/'flex',race)
        envfile=race/'control/environment.flex';text=envfile.read_text()
        text=prepare.once(text,'    let guarded_scene=sg_snapshot(scene);','''    let guarded_scene=sg_snapshot(scene);
    pl_write(1,"GUARD_READY\\n",12);let barrier=alloc(1);vc_require(syscall(0,0,barrier,1,0,0,0)==1,"test barrier failed");''')
        envfile.write_text(text);binary=self.work/'guard-race-test'
        subprocess.run([str(prepare.COMPILER),str(race/'control/main.flex'),'-o',str(binary)],cwd=ROOT,check=True,capture_output=True,timeout=60)
        source=self.work/'case-allowed';source.write_bytes(self.case);bad=self.work/'case-reserved';bad.write_bytes(self.reserved_case)
        (self.scene/'case.json').unlink();(self.scene/'case.json').symlink_to(source)
        layout_good=self.work/'layout-allowed';layout_good.write_bytes(self.layout)
        layout_bad=self.work/'layout-reserved';layout_bad.write_text('{"fit":false,"reservedHeldOut":true}')
        (self.scene/'layout.json').unlink();(self.scene/'layout.json').symlink_to(layout_good)
        process=subprocess.Popen(self.command(binary=binary),cwd=self.home,env=self.environment_vars(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            ready,_,_=select.select([process.stdout],[],[],10);self.assertTrue(ready,'snapshot barrier not reached')
            self.assertEqual(process.stdout.readline(),'GUARD_READY\n')
            (self.scene/'case.json').unlink();(self.scene/'case.json').symlink_to(bad)
            (self.scene/'layout.json').unlink();(self.scene/'layout.json').symlink_to(layout_bad)
            stdout,stderr=process.communicate('x',timeout=15)
            self.assertTrue(self.sentinel.exists(),stderr)
            self.assertEqual((self.output/'110000/scene/case.json').read_bytes(),self.case)
            self.assertEqual((self.output/'110000/scene/layout.json').read_bytes(),self.layout)
            self.assertNotEqual((self.output/'110000/scene/case.json').read_bytes(),bad.read_bytes())
        finally:
            if process.poll() is None:process.kill();process.wait()

    def test_modified_destination_is_rejected_before_simulator_spawn(self):
        race=self.work/'copy-race-source';shutil.copytree(self.build/'flex',race)
        guard=race/'control/holdout-scene-guard.flex';text=guard.read_text()
        text=prepare.once(text,'    let path=sg_path(world,name);vc_write(path,load64(file),load64(file+8));',
'''    let path=sg_path(world,name);vc_write(path,load64(file),load64(file+8));
    if pl_equal(name,"case.json") {pl_write(1,"COPY_READY\\n",11);let barrier=alloc(1);vc_require(syscall(0,0,barrier,1,0,0,0)==1,"test barrier failed");}''')
        guard.write_text(text);binary=self.work/'copy-race-test'
        subprocess.run([str(prepare.COMPILER),str(race/'control/main.flex'),'-o',str(binary)],cwd=ROOT,check=True,capture_output=True,timeout=60)
        process=subprocess.Popen(self.command(binary=binary),cwd=self.home,env=self.environment_vars(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            ready,_,_=select.select([process.stdout],[],[],10);self.assertTrue(ready,'copy barrier not reached')
            self.assertEqual(process.stdout.readline(),'COPY_READY\n')
            (self.output/'110000/scene/case.json').write_bytes(self.reserved_case)
            stdout,stderr=process.communicate('x',timeout=15)
            self.assertNotEqual(process.returncode,0);self.assertIn('guard: copied scene digest mismatch',stderr);self.assertFalse(self.sentinel.exists())
        finally:
            if process.poll() is None:process.kill();process.wait()

    def test_build_refuses_existing_destination(self):
        with self.assertRaises(FileExistsError):prepare.prepare(self.build)

    def test_repeated_snapshot_memory_is_bounded(self):
        # Test-only entry point exercises the real guard snapshot/release path.
        # A 512 KiB fitting environment repeated 48 times would retain at
        # least 24 MiB without releasing scene buffers.
        (self.scene/'environment.bin').write_bytes(b'x'*(512*1024))
        copied=self.work/'memory-source';shutil.copytree(self.build/'flex',copied)
        main=copied/'control/main.flex';text=main.read_text()
        text=prepare.once(text,'fn main(argc,argv) {','fn sg_original_main(argc,argv) {')
        text+='''\nfn sg_test_rss_pages() {
    let fd=syscall(2,"/proc/self/statm",0,0,0,0,0);vc_require(fd>=0,"cannot read statm");let buf=alloc(256);
    let n=syscall(0,fd,buf,255,0,0,0);syscall(3,fd,0,0,0,0,0);vc_require(n>0,"cannot read resident pages");
    let i=0;while i<n && load8(buf+i)!=32 {i=i+1;}while i<n && load8(buf+i)==32 {i=i+1;}
    let start=i;while i<n && load8(buf+i)>=48 && load8(buf+i)<=57 {i=i+1;}
    let pages=pl_integer(buf+start,i-start);vc_require(!pl_bad_number && i>start,"invalid resident pages");syscall(11,buf,256,0,0,0,0);return pages;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==2,"expected scene");
    sg_init(pl_environment(argc,argv,"PUPPYBOT_RESERVED_MANIFEST"),pl_environment(argc,argv,"PUPPYBOT_RESERVED_MANIFEST_SHA256"));
    let initial=sg_test_rss_pages();
    let i=0;while i<48 {let snapshot=sg_snapshot(load64(argv+8));sg_release(snapshot);i=i+1;}
    let final=sg_test_rss_pages();let b=alloc(32);let out=alloc(128);pl_builder(b,out,128);pl_int(b,initial);pl_char(b,32);pl_int(b,final);pl_char(b,10);pl_print(1,out);return 0;
}\n'''
        main.write_text(text);binary=self.work/'memory-test'
        subprocess.run([str(prepare.COMPILER),str(main),'-o',str(binary)],cwd=ROOT,check=True,capture_output=True,timeout=60)
        result=subprocess.run([str(binary),str(self.scene)],cwd=self.home,env=self.environment_vars(),capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        initial,final=map(int,result.stdout.split());growth=(final-initial)*os.sysconf('SC_PAGE_SIZE')
        self.assertLess(growth,8*1024**2,'repeated scene snapshots retained too much resident memory')
        # Negative control verifies that the same measurement catches the
        # original bug, rather than passing because of inherited peak RSS.
        main.write_text(prepare.once(text,'sg_release(snapshot);','if snapshot {}'))
        leaky=self.work/'memory-leak-control'
        subprocess.run([str(prepare.COMPILER),str(main),'-o',str(leaky)],cwd=ROOT,check=True,capture_output=True,timeout=60)
        leak=subprocess.run([str(leaky),str(self.scene)],cwd=self.home,env=self.environment_vars(),capture_output=True,text=True,timeout=20)
        self.assertEqual(leak.returncode,0,leak.stderr);before,after=map(int,leak.stdout.split())
        self.assertGreater((after-before)*os.sysconf('SC_PAGE_SIZE'),16*1024**2,'RSS fixture did not detect intentionally retained snapshots')


if __name__=='__main__':unittest.main()

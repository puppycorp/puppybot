"""Independent small-network numerical checks and malformed Pup/checkpoint cases."""
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
COMPILER = os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT.parent/'flexscript/build/flex'))
MODEL = '''x=input("observation",[1,2,4,4])
c=conv2d(x,"test",4,3,1,1,1,2)
s=sigmoid(c)
a=c*s
p=maxpool2d(a,5,1,2)
u=upsample2d(p,2)
l=slice(u,1,1,3)
v=concat(l,l,1)
r=reshape(v,[1,2,16,8])
t=permute(r,[0,1,3,2])
m=batch_matmul(r,t)
g=m*.125
q=softmax(g,-1)
z=batch_matmul(q,r)
output z
'''


def checkpoint(directory, tensors):
    payload = bytearray()
    records = bytearray()
    for name, shape, values in tensors:
        data = struct.pack('<'+'f'*len(values), *values)
        dims = shape+[1]*(4-len(shape))
        records.extend(struct.pack('<192sQQQ4q8x', name.encode(), len(shape), len(values), len(payload), *dims))
        payload.extend(data)
    data = struct.pack('<8sQQQ', b'PUPV0001', len(tensors), 32+len(records), len(payload))+records+payload
    (directory/'weights.bin').write_bytes(data)
    manifest = dict(schema='puppybot.detector.v1', runtime='pup', weights='weights.bin',
                    weightsSha256=hashlib.sha256(data).hexdigest())
    (directory/'model.json').write_text(json.dumps(manifest))


def reference(x, w, bias):
    conv = []
    for c in range(4):
        for y in range(4):
            for xx in range(4):
                total = bias[c]
                for ky in range(3):
                    for kx in range(3):
                        iy, ix = y+ky-1, xx+kx-1
                        if 0 <= iy < 4 and 0 <= ix < 4:
                            total += x[(c//2)*16+iy*4+ix]*w[c*9+ky*3+kx]
                conv.append(total/(1+math.exp(-total)))
    pooled = [max(conv[c*16+iy*4+ix] for iy in range(max(0,y-2),min(4,y+3))
                  for ix in range(max(0,xx-2),min(4,xx+3)))
              for c in range(4) for y in range(4) for xx in range(4)]
    up = [pooled[c*16+(y//2)*4+xx//2] for c in range(4) for y in range(8) for xx in range(8)]
    r = (up[64:192]*2)
    result = []
    for b in range(2):
        matrix = [r[b*128+i*8:b*128+(i+1)*8] for i in range(16)]
        for row in matrix:
            attention = [sum(a*b for a,b in zip(row,other))*.125 for other in matrix]
            maximum = max(attention)
            weights = [math.exp(v-maximum) for v in attention]
            weights = [v/sum(weights) for v in weights]
            result.extend(sum(weights[j]*matrix[j][k] for j in range(16)) for k in range(8))
    return result


def indexing(directory, backends):
    rng = random.Random(42)
    pairs = [(a, b) for a in (0, 1, 16777215, 16777216)
             for b in (1, 2, 3, 7, 31, 160, 640, 16777215, 16777216)]
    pairs += [(rng.randrange(16777217), rng.randrange(1, 16777217)) for _ in range(512)]
    values, expected = [], []
    for i, (a, b) in enumerate(pairs):
        value = (-115.5, -.5, -.49999, 0, .49999, .5, 115.5)[i % 7]
        bits = struct.unpack('<I', struct.pack('<f', value))[0]
        values.extend((a, b, bits))
        expected.extend((a//b, a%b, math.floor(abs(value)+.5)*(-1 if value < 0 else 1)))
    input_path, output_path = directory/'indices.bin', directory/'quotients.bin'
    input_path.write_bytes(struct.pack('<'+'Q'*len(values), *values))
    kernel = directory/'indexing.flex'
    kernel.write_text(f'''import "{ROOT}/flex/ml/kernels/ops.flex";
fn kernel(index,input,output,count) {{if index<count {{let a=load64(input+index*24);let b=load64(input+index*24+8);store64(output+index*24,vk_quotient(a,b));store64(output+index*24+8,vk_remainder(a,b));store64(output+index*24+16,vk_round(gpu_load_u32(input+index*24+16)));}}return 0;}}
fn main() {{return 78;}}
''')
    if backends:
        for target, suffix in [('sass-sm75', 'cubin'), ('ptx', 'ptx'), ('hip', 'hip')]:
            subprocess.run([COMPILER, '--target', target, str(kernel), '-o',
                            str(directory/('indexing.'+suffix))], check=True)
    host = directory/'index-host.flex'
    host.write_text(f'''import "{ROOT}/flex/vision/backend.flex";
fn pup_model_input(name) {{return 0;}}
fn main(argc,argv) {{pl_init();vp_init(".",vp_backend_parse(load64(argv+24)),0);let data=alloc(65536);let n=pl_read_file(load64(argv+8),data,65535);let count=n/24;let output=alloc(n);
if vp_backend {{let suffix=".ptx";if vp_backend==1 {{suffix=".hip";}}if vp_backend==3 {{suffix=".cubin";}}let image=vp_map(vp_suffix("{directory}/indexing",suffix));let module=device_module(image);vp_require(module,device_error());let input=vp_buffer(n);let result=vp_buffer(n);vp_upload(input,data,n);vp_check(device_launch(module,input,result,count));vp_check(device_synchronize());vp_check(device_download(output,result,n));}}
else {{let i=0;while i<count {{let a=load64(data+i*24);let b=load64(data+i*24+8);store64(output+i*24,vk_quotient(a,b));store64(output+i*24+8,vk_remainder(a,b));store64(output+i*24+16,vk_round(pb_u32(data+i*24+16)));i=i+1;}}}}return pl_atomic_file(load64(argv+16),output,n);}}
''')
    binary = directory/'index-host'
    subprocess.run([COMPILER, str(host), '-o', str(binary)], check=True)
    for backend in ['cpu', *backends]:
        subprocess.run([str(binary), str(input_path), str(output_path), backend], check=True, timeout=15)
        assert struct.unpack('<'+'q'*len(expected), output_path.read_bytes()) == tuple(expected), backend
    return len(expected)*(1+len(backends))


def bindings(directory, backends):
    source, factory = directory/'bindings.pup', directory/'bindings-factory.flex'
    source.write_text('a=input("left",[2,2,2])\nb=input("right",[2,2,2])\noutput a+b,a*b\n')
    subprocess.run([str(ROOT/'build/flex/compile-pup'), str(source), str(factory)], check=True)
    checkpoint(directory, [])
    sha = hashlib.sha256((directory/'weights.bin').read_bytes()).hexdigest()
    host = directory/'bindings.flex'
    host.write_text(f'''import "{ROOT}/flex/ml/runtime.flex";
import "{factory}";
fn main(argc,argv) {{pl_init();vp_init("{ROOT}/build/flex/pup-kernels",vp_backend_parse(load64(argv+8)),0);vp_checkpoint_open("{directory}/weights.bin","{sha}");pup_build_model();vp_require(load64(vp_inputs)==2 && load64(vp_outputs)==2,"binding count mismatch");let data=alloc(64);let i=0;
while i<2 {{let j=0;while j<8 {{pb_put32(data+j*4,pb_f64_to_f32(f64_from_i64(i*8+j+1)));j=j+1;}}vp_upload(load64(vp_at(vp_at(vp_inputs,i),1)),data,32);i=i+1;}}
vp_execute();i=0;while i<2 {{vp_read_tensor(vp_at(vp_outputs,i),data+i*32);i=i+1;}}return pl_atomic_file(load64(argv+16),data,64);}}
''')
    binary, output = directory/'bindings', directory/'bindings.bin'
    subprocess.run([COMPILER, str(host), '-o', str(binary)], check=True)
    expected = tuple(a+(a+8) for a in range(1, 9))+tuple(a*(a+8) for a in range(1, 9))
    for backend in ['cpu', *backends]:
        subprocess.run([str(binary), backend, str(output)], check=True, timeout=15)
        assert struct.unpack('<16f', output.read_bytes()) == expected
    return len(expected)*(1+len(backends))


def placements(directory, backends):
    source, factory = directory/'placements.pup', directory/'placements-factory.flex'
    source.write_text('''x=input("x",[1,4,2,3])
a=x+1
b=x*2
c=concat(a,b,1)
v=slice(c,1,1,7)
d=v*.5
e=x-3
r=concat(d,e,1)
z=x+4
s=concat(r,z,1)
output s,c
''')
    subprocess.run([str(ROOT/'build/flex/compile-pup'),str(source),str(factory)],check=True)
    checkpoint(directory,[])
    sha = json.loads((directory/'model.json').read_text())['weightsSha256']
    host, binary = directory/'placements.flex', directory/'placements'
    host.write_text(f'''import "{ROOT}/flex/vision/backend.flex";
import "{factory}";
fn main(argc,argv) {{pl_init();if argc==2 {{vp_init(".",0,0);vp_compile_only=1;pup_build_model();let inventory=vp_plan_inventory();return pl_atomic_file(load64(argv+8),inventory,load64(vp_nodes)*224);}}
vp_init(load64(argv+16),vp_backend_parse(load64(argv+8)),0);vp_checkpoint_open("{directory}/weights.bin","{sha}");pup_build_model();let data=alloc(528);let i=0;while i<24 {{pb_put32(data+i*4,gpu_f32_from_i64(i-12));i=i+1;}}vp_upload(load64(vp_input),data,96);vp_execute();vp_read_tensor(vp_at(vp_outputs,0),data);vp_read_tensor(vp_at(vp_outputs,1),data+336);return pl_atomic_file(load64(argv+24),data,528);}}
''')
    subprocess.run([COMPILER,str(host),'-o',str(binary)],check=True)
    inventory, kernels = directory/'placements.bin', directory/'placements-kernels'
    subprocess.run([str(binary),str(inventory)],check=True)
    kernels.mkdir()
    for path in (ROOT/'build/flex/pup-kernels').iterdir():
        if path.suffix in ('.ptx','.cubin','.hip'):
            shutil.copyfile(path,kernels/path.name)
    subprocess.run(['python3',str(ROOT/'flex/ml/codegen.py'),str(inventory),
                    '--compiler',COMPILER,'--output',str(kernels)],check=True)
    plan = json.loads((kernels/'plan.json').read_text())
    assert plan['views']==1 and plan['nodes']-plan['launches']==4
    x = list(range(-12,12))
    c = [v+1 for v in x]+[v*2 for v in x]
    expected = tuple([v*.5 for v in c[6:42]]+[v-3 for v in x]+[v+4 for v in x]+c)
    output = directory/'placement-output.bin'
    for backend in ['cpu',*backends]:
        subprocess.run([str(binary),backend,str(kernels),str(output)],check=True,timeout=15)
        assert struct.unpack('<132f',output.read_bytes())==expected, backend
    checks = len(expected)*(1+len(backends))+1
    if backends:
        path = next(kernels.glob('plan-*.bin'))
        original = path.read_bytes()
        alias = next(80+i*128 for i in range(plan['nodes']) if struct.unpack_from('<Q',original,80+i*128+112)[0])
        for field,value,message in ((112,2**64-1,'invalid tensor placement'),
                                    (120,1,'invalid tensor placement'),
                                    (120,2**63-4,'tensor placement exceeds destination')):
            invalid = bytearray(original)
            struct.pack_into('<Q',invalid,alias+field,value)
            path.write_bytes(invalid)
            failure = subprocess.run([str(binary),backends[0],str(kernels),str(output)],capture_output=True,text=True,timeout=15)
            assert failure.returncode != 0 and message in failure.stderr
            checks += 1
        path.write_bytes(original)
    return checks


def main():
    checks = 0
    with tempfile.TemporaryDirectory(prefix='puppybot-pup-') as temp:
        directory = Path(temp)
        source = directory/'model.pup'
        source.write_text(MODEL)
        factory = directory/'factory.flex'
        subprocess.run([str(ROOT/'build/flex/compile-pup'), str(source), str(factory)], check=True)
        probe = directory/'probe.flex'
        probe.write_text(f'''import "{ROOT}/flex/vision/backend.flex";
import "{factory}";
fn main(argc,argv) {{pl_init();let backend=0;if argc>4 {{backend=vp_backend_parse(load64(argv+32));}}let kernels="{ROOT}/build/flex/pup-kernels";if argc>5 {{kernels=load64(argv+40);}}vp_begin(load64(argv+8),kernels,backend);pup_build_model();let data=alloc(1048577);let n=pl_read_file(load64(argv+16),data,1048576);vp_require(n==load64(vp_input+8)*4,"input length mismatch");vp_upload(load64(vp_input),data,n);vp_execute();vp_read_output(data);return pl_atomic_file(load64(argv+24),data,load64(vp_output+8)*4);}}
''')
        binary = directory/'probe'
        subprocess.run([COMPILER,str(probe),'-o',str(binary)],check=True)
        x = [(i%11-5)*.07 for i in range(32)]
        w = [(i%7-3)*.04 for i in range(36)]
        bias = [-.4,.2,-.1,.3]
        checkpoint(directory,[('test.weight',[4,1,3,3],w),('test.bias',[4],bias)])
        (directory/'input.bin').write_bytes(struct.pack('<32f',*x))
        args = [str(binary),str(directory/'model.json'),str(directory/'input.bin'),str(directory/'output.bin')]
        subprocess.run(args,check=True,timeout=15)
        expected = reference(x,w,bias)
        actual = struct.unpack('<256f',(directory/'output.bin').read_bytes())
        assert max(abs(a-b) for a,b in zip(actual,expected)) < 3e-6
        checks += len(actual)
        backends = os.environ.get('PUPPYBOT_TEST_BACKENDS', 'auto' if os.environ.get('PUPPYBOT_TEST_GPU') == '1' else '').split()
        for backend in backends:
            subprocess.run([*args,backend],check=True,timeout=15)
            gpu = struct.unpack('<256f',(directory/'output.bin').read_bytes())
            assert max(abs(a-b) for a,b in zip(gpu,expected)) < 3e-6
            checks += len(gpu)
        if backends:
            describe = directory/'describe.flex'
            describe.write_text(f'''import "{ROOT}/flex/vision/backend.flex";
import "{factory}";
fn main(argc,argv) {{pl_init();vp_compile_only=1;vp_init(".",0,0);pup_build_model();let data=vp_plan_inventory();return pl_atomic_file(load64(argv+8),data,load64(vp_nodes)*224);}}
''')
            subprocess.run([COMPILER,str(describe),'-o',str(directory/'describe')],check=True)
            inventory = directory/'graph.bin'
            subprocess.run([str(directory/'describe'),str(inventory)],check=True)
            for mode in ('fp32','fp32-tc'):
                kernels = directory/mode
                kernels.mkdir()
                for path in (ROOT/'build/flex/pup-kernels').iterdir():
                    if path.suffix in ('.ptx','.cubin','.hip'):
                        shutil.copyfile(path,kernels/path.name)
                subprocess.run(['python3',str(ROOT/'flex/ml/codegen.py'),str(inventory),
                                '--compiler',COMPILER,'--output',str(kernels),'--math',mode],check=True)
                for backend in backends:
                    if mode=='fp32-tc' and backend not in ('sass','cuda','auto'): continue
                    subprocess.run([*args,backend,str(kernels)],check=True,timeout=15)
                    gpu = struct.unpack('<256f',(directory/'output.bin').read_bytes())
                    assert max(abs(a-b) for a,b in zip(gpu,expected)) < 3e-6, (mode,backend)
                    checks += len(gpu)
                    if mode=='fp32-tc':
                        for value in (1e8,float('inf')):
                            (directory/'invalid.bin').write_bytes(struct.pack('<32f',*([value]*32)))
                            failure = subprocess.run([args[0],args[1],str(directory/'invalid.bin'),args[3],backend,str(kernels)],capture_output=True,text=True,timeout=15)
                            assert failure.returncode != 0 and 'finite FP16 range' in failure.stderr
                            checks += 1
        checks += indexing(directory, backends)
        manifest = json.loads((directory/'model.json').read_text())
        manifest['weightsSha256'] = '0'*64
        (directory/'model.json').write_text(json.dumps(manifest))
        failure = subprocess.run(args,capture_output=True,text=True,timeout=10)
        assert failure.returncode != 0 and 'SHA256 mismatch' in failure.stderr
        checks += 1
        checkpoint(directory,[('test.weight',[4,2,3,3],w*2),('test.bias',[4],bias)])
        failure = subprocess.run(args,capture_output=True,text=True,timeout=10)
        assert failure.returncode != 0 and 'shape differs' in failure.stderr
        checks += 1
        checkpoint(directory,[('other.weight',[4,1,3,3],w),('test.bias',[4],bias)])
        failure = subprocess.run(args,capture_output=True,text=True,timeout=10)
        assert failure.returncode != 0 and 'tensor is missing' in failure.stderr
        checks += 1
        for expression in ('slice(x,1,2,1)','concat(x,x,8)','upsample2d(x,0)',
                           'softmax(x,4)','batch_matmul(x,x)','reshape(x,[1,33])'):
            source.write_text('x=input("images",[1,2,3,4])\noutput '+expression+'\n')
            failure = subprocess.run([str(ROOT/'build/flex/compile-pup'),str(source),str(factory)],capture_output=True,text=True)
            assert failure.returncode != 0 and 'error:' in failure.stderr, expression
            checks += 1
        checks += bindings(directory, backends)
        checks += placements(directory, backends)
    print(f'Native Pup vision: {checks} numerical and malformed graph/checkpoint checks passed')


if __name__ == '__main__':
    main()

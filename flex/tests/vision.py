"""Independent small-network numerical checks and malformed Pup/checkpoint cases."""
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
COMPILER = os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT.parent/'flexscript/build/flex'))
MODEL = '''x=input("images",[1,2,4,4])
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
fn main(argc,argv) {{pl_init();vp_begin(load64(argv+8),load64(argv+32),argc==5);pup_build_detector();let data=alloc(1048577);let n=pl_read_file(load64(argv+16),data,1048576);vp_require(n==load64(vp_input+8)*4,"input length mismatch");vp_upload(load64(vp_input),data,n);vp_execute();vp_read_output(data);return pl_atomic_file(load64(argv+24),data,load64(vp_output+8)*4);}}
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
        if os.environ.get('PUPPYBOT_TEST_GPU') == '1':
            subprocess.run([*args,str(ROOT/'build/flex/vision-kernel.hip')],check=True,timeout=15)
            gpu = struct.unpack('<256f',(directory/'output.bin').read_bytes())
            assert max(abs(a-b) for a,b in zip(gpu,expected)) < 3e-6
            checks += len(gpu)
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
    print(f'Native Pup vision: {checks} numerical and malformed graph/checkpoint checks passed')


if __name__ == '__main__':
    main()

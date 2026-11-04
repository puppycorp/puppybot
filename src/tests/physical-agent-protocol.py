# Rendered hybrid simulator transport smoke; requires an idle GPU.
# Usage: python3 -I flex/tests/physical-agent-protocol.py SIMULATOR
import json,os,socket,struct,subprocess,sys,tempfile

if len(sys.argv) != 2:
    raise SystemExit('usage: physical-agent-protocol.py SIMULATOR')
simulator = sys.argv[1]

def exact(sock,n):
    data=b''
    while len(data)<n:
        b=sock.recv(n-len(data))
        if not b: raise RuntimeError('stream closed after %d of %d bytes'%(len(data),n))
        data+=b
    return data

def run(mode):
    p,c=socket.socketpair();p.settimeout(70)
    log=tempfile.NamedTemporaryFile(prefix='puppy-physical-smoke-',delete=False)
    env=os.environ.copy();env.pop('DISPLAY',None);env.pop('WAYLAND_DISPLAY',None);env['SDL_VIDEODRIVER']='offscreen'
    args=[simulator,'--hidden','--steps','1000000','--case','discover-house-blocks-into-box','--agent-fd',str(c.fileno()),'--agent-physical','--localization','wheel-drift','--no-visual-odometry','--bind','127.0.0.1:0']
    proc=subprocess.Popen(args,pass_fds=(c.fileno(),),stdout=log,stderr=log,env=env);c.close()
    def call(seq,cmd,steering=0,speed=0,hold=0,task=4):
        p.sendall(struct.pack('<8q',cmd,seq,steering,speed,hold,0,task,0))
        js,rgb,n,blocked=struct.unpack('<4q',exact(p,32));assert 0<js<=16384 and rgb==921600 and n==seq and blocked==0,(js,rgb,n,blocked)
        x=json.loads(exact(p,js));image=exact(p,rgb)
        assert set(x)=={'schema','sequence','step','timeMs','owner','ack','imageValid','rgbDetections','driveCommand','jointTicks','totalSteps','cameraFrame','cameraDriving','cameraStill'},x
        assert x['schema']=='puppybot.physical-agent.v1' and x['sequence']==seq
        if not x['imageValid']: assert image == bytes(rgb)
        return x
    try:
        x=call(1,1);assert x['owner']==0 and x['ack']==0 and x['imageValid'] and x['cameraDriving'] and x['cameraStill'] and x['cameraFrame']==x['totalSteps']
        ticks=x['jointTicks'];last=x['totalSteps']
        x=call(2,2,0,0,10);assert x['ack']==1 and x['owner']==0 and x['cameraDriving'] and x['cameraStill'] and x['jointTicks']==ticks and x['cameraFrame']==x['totalSteps']==last+10
        if mode=='stop':
            x=call(3,3);assert x['ack']==7 and x['owner']==2 and x['driveCommand'][:2]==[0,0]
            code=proc.wait(timeout=20);assert code==0,(code,log.name)
        else:
            x=call(3,4);assert x['ack']==6 and x['owner']==2 and x['driveCommand'][:2]==[0,0]
            code=proc.wait(timeout=20);assert code==1,(code,log.name)
        print(mode,'passed', 'log',log.name, flush=True)
    finally:
        p.close()
        if proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
        log.close()

for name in ('stop','invalid'):run(name)

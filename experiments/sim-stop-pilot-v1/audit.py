#!/usr/bin/env python3
"""Read-only independent replay of a paired simulated stop diagnostic."""
import hashlib
import json
import struct
from pathlib import Path

HEADER=struct.Struct('<BQ')
REQUEST=struct.Struct('<8q')
FRAME=struct.Struct('<4q')
RGB=640*480*3


def pairs(items):
    result={}
    for key,value in items:
        if key in result:raise ValueError('duplicate JSON key')
        result[key]=value
    return result


def number(value):
    result=int(value)
    if not -(1<<63)<=result<(1<<63):raise ValueError('oversized integer')
    return result


def invalid(value):raise ValueError('nonfinite JSON constant: '+value)


def records(path):
    data=Path(path).read_bytes();offset=0;out=[]
    while offset<len(data):
        if len(data)-offset<HEADER.size:raise ValueError('truncated protocol record header')
        kind,size=HEADER.unpack_from(data,offset);offset+=HEADER.size
        if kind not in range(1,7) or size>RGB+65568 or size>len(data)-offset:raise ValueError('invalid protocol record')
        out.append((kind,data[offset:offset+size]));offset+=size
    return out


def response(wire,sequence):
    if len(wire)<FRAME.size:raise ValueError('short response')
    size,rgb,seq,reserved=FRAME.unpack_from(wire)
    if not 0<size<=65536 or rgb!=RGB or seq!=sequence or reserved or len(wire)!=FRAME.size+size+rgb:raise ValueError('bad response framing')
    row=json.loads(wire[FRAME.size:FRAME.size+size],object_pairs_hook=pairs,parse_int=number,parse_constant=invalid)
    keys={'schema','sequence','step','timeMs','owner','ack','imageValid','rgbDetections','totalSteps','cameraFrame','cameraDriving','cameraStill','driveCommand','jointTicks'}
    if not isinstance(row,dict) or set(row)!=keys or row['schema']!='puppybot.physical-agent.v1' or row['sequence']!=seq:raise ValueError('bad response schema or sequence')
    for key in ('sequence','step','timeMs','owner','ack','totalSteps','cameraFrame'):
        if type(row[key]) is not int:raise ValueError('bad integer')
    if row['step']!=row['totalSteps'] or row['timeMs']<0 or row['step']<0:raise ValueError('bad tick')
    for key in ('imageValid','cameraDriving','cameraStill'):
        if type(row[key]) is not bool:raise ValueError('bad camera flag')
    if not isinstance(row['driveCommand'],list) or len(row['driveCommand'])!=3 or not all(type(x) is int for x in row['driveCommand']):raise ValueError('bad drive')
    if not isinstance(row['jointTicks'],list) or len(row['jointTicks'])!=4 or not all(type(x) is int for x in row['jointTicks']):raise ValueError('bad joints')
    return row,wire[FRAME.size+size:]


def stopped(row,pixels):
    if (row['owner'],row['ack'],row['driveCommand'])!=(2,7,[0,0,90]):raise ValueError('no explicit zero-drive stop acknowledgement')
    if row['imageValid'] or row['cameraDriving'] or row['cameraStill'] or row['cameraFrame']!=-1 or row['rgbDetections'] is not None or any(pixels):raise ValueError('invalid stopped frame')


def read_session(root):
    root=Path(root);state=json.loads((root/'session.json').read_text(),object_pairs_hook=pairs,parse_int=number,parse_constant=invalid)
    outer=json.loads((root/'outer-monitor/supervisor-result.json').read_text(),object_pairs_hook=pairs,parse_int=number,parse_constant=invalid)
    if (type(outer.get('processGroup')) is not int or outer['processGroup']<=0 or type(outer['clientExit']) is not int or outer['clientExit']!=0
            or outer['timedOut'] is not False or outer['remainingWorkersTerminated'] is not False or outer['signal'] is not None):raise ValueError('unclean supervisor')
    if state['physicalStop']!='unverified' or state['delivery']!='unverified':raise ValueError('invalid physical claim')
    return state,records(root/'protocol.bin')


def initial(entries):
    if len(entries)<3 or [x[0] for x in entries[:3]]!=[1,2,5]:raise ValueError('missing reset transaction')
    request=REQUEST.pack(1,1,0,0,0,0,4,0)
    if entries[0][1]!=request or entries[1][1]!=request:raise ValueError('bad reset request')
    row,pixels=response(entries[2][1],1)
    if (row['owner'],row['ack'],row['driveCommand'])!=(0,0,[0,0,90]) or not row['imageValid'] or not row['cameraDriving'] or not row['cameraStill'] or row['cameraFrame']!=row['totalSteps'] or type(row['rgbDetections']) is not int or row['rgbDetections']<0:raise ValueError('bad reset observation')
    return row


def control_exchange(request,row,pixels,previous):
    cmd,seq,steer,speed,hold,reserved,task,tail=REQUEST.unpack(request)
    if reserved or task!=4 or tail:raise ValueError('invalid control request')
    allowed={1:{(0,0)},2:{(0,1)},3:{(2,7)},6:{(0,2),(1,3)},7:{(1,4),(2,5),(2,6)}}
    if cmd not in allowed or (row['owner'],row['ack']) not in allowed[cmd]:raise ValueError('bad control acknowledgment')
    if cmd in (1,3,6) and (steer or speed or hold):raise ValueError('bad control no-motion request')
    if cmd==2 and (not -1000<=steer<=1000 or not -1000<=speed<=1000 or not 1<=hold<=20):raise ValueError('bad control drive request')
    if cmd==7 and (steer or speed or not 1<=hold<=20):raise ValueError('bad control collector request')
    if previous is not None:
        diff=row['totalSteps']-previous['totalSteps']
        if row['timeMs']-previous['timeMs']!=20*diff:raise ValueError('bad control clock')
        if (cmd==2 and diff!=hold) or (cmd==6 and diff!=2) or (cmd==3 and diff!=0) or (cmd==7 and (diff<0 or diff>hold or (row['ack']==4 and diff!=hold))):raise ValueError('bad control advancement')
        if (cmd in (2,6) and previous['owner']!=0) or (cmd==7 and previous['owner']!=1) or cmd==1:raise ValueError('bad control ownership')
    if cmd==2:
        throttle=int(speed*60/1000) if abs(speed)>=80 else 0
        if row['driveCommand']!=[throttle,throttle,90+int(int(steer/10)*45/100)]:raise ValueError('bad control drive echo')
    elif cmd in (1,3,6) or (cmd==7 and row['ack'] in (5,6)):
        if row['driveCommand']!=[0,0,90]:raise ValueError('bad control stop echo')
    if row['owner']==0:
        if not row['imageValid'] or not row['cameraDriving'] or not row['cameraStill'] or row['cameraFrame']!=row['totalSteps'] or type(row['rgbDetections']) is not int or row['rgbDetections']<0:raise ValueError('bad control image')
        if previous is not None and row['jointTicks']!=previous['jointTicks']:raise ValueError('navigation joints changed')
    elif row['imageValid'] or row['cameraDriving'] or row['cameraStill'] or row['cameraFrame']!=-1 or row['rgbDetections'] is not None or any(pixels):raise ValueError('bad control blank frame')
    if row['ack']==6:raise ValueError('control reported failure')


def audit(control,fault):
    control_state,control_records=read_session(control);fault_state,fault_records=read_session(fault)
    control_initial=initial(control_records);fault_initial=initial(fault_records)
    expected_control={'status':'client_stop_acknowledged','reason':'client requested stop','clientExit':0,'simulatorExit':0,'signal':None,
                      'stopAttempted':False,'stopAcknowledged':True,'stopCommandSource':'client','peerReportedZeroDrive':False}
    if any(k not in control_state or type(control_state[k]) is not type(v) or control_state[k]!=v for k,v in expected_control.items()):raise ValueError('control session inconsistent')
    # Validate complete control record grouping and final on-wire client stop.
    if len(control_records)%3 or any([control_records[i+j][0] for j in range(3)]!=[1,2,5] for i in range(0,len(control_records),3)):raise ValueError('incomplete control protocol')
    if type(control_state.get('lastCompletedSequence')) is not int or control_state['lastCompletedSequence']!=len(control_records)//3:raise ValueError('control session sequence mismatch')
    previous=None
    for i in range(0,len(control_records),3):
        request=control_records[i][1]
        if len(request)!=REQUEST.size or request!=control_records[i+1][1]:raise ValueError('control request mismatch')
        cmd,seq,*_=REQUEST.unpack(request)
        if seq!=i//3+1:raise ValueError('control sequence gap')
        if cmd==3 and i!=len(control_records)-3:raise ValueError('control has an early stop')
        row,pixels=response(control_records[i+2][1],seq)
        control_exchange(request,row,pixels,previous);previous=row
        if i==len(control_records)-3:
            if cmd!=3:raise ValueError('control missing final stop')
            stopped(row,pixels)
    if len(fault_records)!=7 or [x[0] for x in fault_records]!=[1,2,5,6,3,4,5] or fault_records[3][1]!=b'client-killed-after-reset':raise ValueError('missing fault boundary or stop records')
    stop_request=REQUEST.pack(3,2,0,0,0,0,4,0)
    if fault_records[4][1]!=stop_request or fault_records[5][1]!=stop_request:raise ValueError('bad supervisor stop request')
    row,pixels=response(fault_records[6][1],2);stopped(row,pixels)
    if row['totalSteps']!=fault_initial['totalSteps'] or row['timeMs']!=fault_initial['timeMs']:raise ValueError('stop tick differs from boundary')
    expected_fault={'status':'failed','reason':'predeclared client loss after completed reset','clientExit':-9,'simulatorExit':0,'signal':None,
                    'stopAttempted':True,'stopAcknowledged':True,'stopCommandSource':'supervisor','peerReportedZeroDrive':False,'lastCompletedSequence':1}
    if any(k not in fault_state or type(fault_state[k]) is not type(v) or fault_state[k]!=v for k,v in expected_fault.items()):raise ValueError('fault session inconsistent')
    matched=control_records[:3]==fault_records[:3]
    return {'status':'simulated_stop_acknowledged' if matched else 'censored_initial_observation_mismatch',
            'initialProtocolBytesMatch':matched,'controlResetSHA256':hashlib.sha256(control_records[2][1]).hexdigest(),
            'faultResetSHA256':hashlib.sha256(fault_records[2][1]).hexdigest(),'stopSequence':2,
            'scope':'saved local journals and supervisor reports; no OS attestation, physical stop or delivery proof'}

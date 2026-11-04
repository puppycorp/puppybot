#!/usr/bin/env python3
"""Bounded simulated physical-protocol proxy; no physical stop claim."""
import json
import math
import select
import socket
import struct
import time

RGB=640*480*3
HEADER=struct.Struct('<4q')
REQUEST=struct.Struct('<8q')
KEYS={'schema','sequence','step','timeMs','owner','ack','imageValid','rgbDetections','totalSteps','cameraFrame','cameraDriving','cameraStill','driveCommand','jointTicks'}


class Interrupted(Exception):pass


def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate peer JSON key')
        result[key]=value
    return result


def invalid_constant(value):
    raise ValueError('nonfinite peer JSON constant: '+value)


def signed_integer(value):
    number=int(value)
    if not -(1<<63)<=number<(1<<63):raise ValueError('peer JSON integer outside signed 64-bit range')
    return number


def read_exact(sock,size,deadline,stop,allow_eof=False):
    data=bytearray()
    while len(data)<size:
        if stop():raise Interrupted('supervisor interrupted')
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('stream deadline')
        if not select.select([sock],[],[],min(remaining,.1))[0]:continue
        try:chunk=sock.recv(size-len(data))
        except (BlockingIOError,InterruptedError):continue
        if not chunk:
            if not data and allow_eof:return None
            raise EOFError('partial or closed stream')
        data.extend(chunk)
    return bytes(data)


def write_all(sock,data,deadline,stop):
    view=memoryview(data)
    while view:
        if stop():raise Interrupted('supervisor interrupted')
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('stream deadline')
        if not select.select([],[sock],[],min(remaining,.1))[1]:continue
        try:n=sock.send(view)
        except (BlockingIOError,InterruptedError):continue
        if n<=0:raise EOFError('closed stream')
        view=view[n:]


def validate_request(raw,sequence,initialized,owner):
    cmd,seq,steer,speed,hold,reserved,task,tail=REQUEST.unpack(raw)
    if seq!=sequence+1 or seq>2147483647 or reserved or tail or task!=4:raise ValueError('invalid request sequence or reserved fields')
    if cmd==1:
        if initialized or seq!=1 or steer or speed or hold:raise ValueError('invalid reset request')
    elif not initialized:raise ValueError('request before reset')
    elif cmd==2:
        if owner!=0 or not -1000<=steer<=1000 or not -1000<=speed<=1000 or not 1<=hold<=20:raise ValueError('invalid drive request')
    elif cmd==6:
        if owner!=0 or steer or speed or hold:raise ValueError('invalid handoff request')
    elif cmd==7:
        if owner!=1 or steer or speed or not 1<=hold<=20:raise ValueError('invalid collector request')
    elif cmd==3:
        if steer or speed or hold:raise ValueError('invalid stop request')
    else:raise ValueError('unknown request')
    return cmd,seq,steer,speed,hold


def read_frame(sock,request,previous,deadline,stop):
    header=read_exact(sock,HEADER.size,deadline,stop)
    size,rgb,sequence,reserved=HEADER.unpack(header)
    cmd,seq,steer,speed,hold=request
    if not 0<size<=65536 or rgb!=RGB or sequence!=seq or reserved:raise ValueError('invalid peer frame header')
    body=read_exact(sock,size,deadline,stop);pixels=read_exact(sock,RGB,deadline,stop)
    row=json.loads(body,object_pairs_hook=unique_object,parse_constant=invalid_constant,parse_int=signed_integer)
    if not isinstance(row,dict) or set(row)!=KEYS or row.get('schema')!='puppybot.physical-agent.v1':raise ValueError('invalid peer schema')
    if any(type(row.get(key)) is not int for key in ('sequence','step','timeMs','owner','ack','totalSteps','cameraFrame')) or row['sequence']!=seq or row['step']!=row['totalSteps'] or row['totalSteps']<0 or row['timeMs']<0:raise ValueError('invalid peer sequence or ticks')
    owner,ack=row['owner'],row['ack']
    allowed={1:{(0,0)},2:{(0,1)},3:{(2,7)},6:{(0,2),(1,3)},7:{(1,4),(2,5),(2,6)}}
    if (owner,ack) not in allowed[cmd]:raise ValueError('invalid peer owner or acknowledgment')
    if type(row['imageValid']) is not bool or type(row['cameraDriving']) is not bool or type(row['cameraStill']) is not bool:raise ValueError('invalid camera flags')
    drive=row['driveCommand'];joints=row['jointTicks']
    if not isinstance(drive,list) or len(drive)!=3 or any(type(x) is not int for x in drive) or not isinstance(joints,list) or len(joints)!=4 or any(type(x) is not int for x in joints):raise ValueError('invalid peer drive or joints')
    if cmd in (1,3,6) or (cmd==7 and ack in (5,6)):
        if drive!=[0,0,90]:raise ValueError('invalid stopped command echo')
    elif cmd==2:
        throttle=int(speed*60/1000) if abs(speed)>=80 else 0
        angle=90+int(int(steer/10)*45/100)
        if drive!=[throttle,throttle,angle]:raise ValueError('invalid drive echo')
    if owner==0:
        if (not row['imageValid'] or not row['cameraDriving'] or not row['cameraStill'] or row['cameraFrame']!=row['totalSteps']
                or type(row['rgbDetections']) is not int or row['rgbDetections']<0):raise ValueError('invalid navigation observation')
        if previous is not None and joints!=previous['jointTicks']:raise ValueError('navigation arm changed')
    elif (row['imageValid'] or row['rgbDetections'] is not None or row['cameraFrame']!=-1 or row['cameraDriving'] or row['cameraStill'] or any(pixels)):
        raise ValueError('collector observation must be a blank invalid frame')
    if previous is not None:
        difference=row['totalSteps']-previous['totalSteps']
        if row['timeMs']-previous['timeMs']!=20*difference:raise ValueError('peer clock does not match ticks')
        if (cmd==2 and difference!=hold) or (cmd==6 and difference!=2) or (cmd==7 and ((ack==4 and difference!=hold) or (ack in (5,6) and not 0<=difference<=hold))) or (cmd==3 and difference!=0):raise ValueError('invalid tick advancement')
    return row,header+body+pixels


def session(upstream,peer,*,io_seconds=5,stop_seconds=2,wall_seconds=30,interrupted=lambda:False,record=lambda *_:None,after_reply=lambda *_:False):
    if not all(type(x) in (int,float) and math.isfinite(x) and x>0 for x in (io_seconds,stop_seconds,wall_seconds)) or wall_seconds>60 or stop_seconds>5:raise ValueError('invalid simulator proxy limits')
    upstream.setblocking(False);peer.setblocking(False);end=time.monotonic()+wall_seconds
    active_end=end-min(stop_seconds,wall_seconds/2)
    result={'status':'failed','reason':None,'stopAttempted':False,'stopAcknowledged':False,'stopCommandSource':None,
            'peerReportedZeroDrive':False,'delivery':'unverified','physicalStop':'unverified','lastCompletedSequence':0}
    last=0;previous=None;owner=0
    def deadline(seconds,stopping=False):return min(end if stopping else active_end,time.monotonic()+seconds)
    def attempt_stop():
        if previous is None or previous['ack'] in (6,7) or last>=2147483647:return
        result['stopAttempted']=True;result['stopCommandSource']='supervisor'
        req=REQUEST.pack(3,last+1,0,0,0,0,4,0)
        try:
            limit=deadline(stop_seconds,True);record(3,req);write_all(peer,req,limit,lambda:False);record(4,req)
            row,wire=read_frame(peer,(3,last+1,0,0,0),previous,limit,lambda:False);record(5,wire)
            if row['ack']==7:result['stopAcknowledged']=True
        except (OSError,ValueError,EOFError,TimeoutError,json.JSONDecodeError):pass
    while True:
        try:
            raw=read_exact(upstream,REQUEST.size,deadline(io_seconds),interrupted,allow_eof=True)
            if raw is None:raise EOFError('client stream closed')
            request=validate_request(raw,last,previous is not None,owner)
        except (OSError,ValueError,EOFError,TimeoutError,Interrupted) as error:
            result['reason']=str(error);attempt_stop();break
        # Once any downstream bytes might have been sent, the sequence state
        # is ambiguous until a complete, validated reply is received.
        try:
            limit=deadline(io_seconds);record(1,raw);write_all(peer,raw,limit,interrupted);record(2,raw)
            row,wire=read_frame(peer,request,previous,limit,interrupted)
            record(5,wire)
        except (OSError,ValueError,EOFError,TimeoutError,Interrupted,json.JSONDecodeError) as error:
            result['reason']='in-flight exchange unverified: '+str(error);break
        last=request[1];previous=row;owner=row['owner'];result['lastCompletedSequence']=last
        if after_reply(last,row):
            result['reason']='predeclared client loss after completed reset';attempt_stop();break
        if row['ack']==6:result['peerReportedZeroDrive']=True
        if row['ack']==7:
            result['stopAcknowledged']=True;result['stopCommandSource']='client'
        try:write_all(upstream,wire,deadline(io_seconds),interrupted)
        except (OSError,EOFError,TimeoutError,Interrupted) as error:
            result['reason']='client reply delivery failed: '+str(error)
            if row['ack'] not in (6,7):attempt_stop()
            break
        if row['ack']==6:
            result['reason']='peer reported failure';break
        if row['ack']==7:
            result['status']='client_stop_acknowledged';result['reason']='client requested stop';break
    return result

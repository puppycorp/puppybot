#!/usr/bin/env python3
"""CPU socket tests of strict transaction-boundary stop semantics."""
import importlib.util
import json
import socket
import struct
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('stop_proxy',HERE/'proxy.py')
proxy=importlib.util.module_from_spec(spec);spec.loader.exec_module(proxy)


def read(sock,n):
    data=bytearray()
    while len(data)<n:
        part=sock.recv(n-len(data))
        if not part:raise EOFError()
        data.extend(part)
    return bytes(data)


def frame(seq,cmd,step,*,bad=None):
    owner,ack={1:(0,0),2:(0,1),3:(2,7),6:(1,3),7:(1,4)}[cmd];valid=owner==0
    drive=[12,12,90] if cmd==2 else [0,0,90]
    if bad=='stop_drive' and cmd==3:drive=[1,1,90]
    row={'schema':'puppybot.physical-agent.v1','sequence':seq,'step':step,'timeMs':step*20,'owner':owner,'ack':ack,
         'imageValid':valid,'rgbDetections':0 if valid else None,'totalSteps':step,'cameraFrame':step if valid else -1,
         'cameraDriving':valid,'cameraStill':valid,'driveCommand':drive,'jointTicks':[1,2,3,4]}
    body=(json.dumps(row)+'\n').encode();sequence=seq+(bad=='wrong_sequence' and cmd in (2,3))
    return proxy.HEADER.pack(len(body),proxy.RGB,sequence,0)+body+bytes(proxy.RGB)


class ProxyTest(unittest.TestCase):
    def setUp(self):
        self.client,self.up=socket.socketpair();self.peer,self.down=socket.socketpair();self.client.settimeout(3);self.peer.settimeout(3)
        self.requests=[];self.results=[];self.errors=[];self.threads=[]

    def tearDown(self):
        for s in (self.client,self.up,self.peer,self.down):
            try:s.close()
            except OSError:pass
        for thread in self.threads:thread.join(timeout=3)

    def start(self,handler=None,**limits):
        def peer():
            step=100
            try:
                while True:
                    request=proxy.REQUEST.unpack(read(self.peer,64));self.requests.append(request);cmd,seq,_,_,hold,*_=request
                    if handler and handler(self.peer,request):return
                    if cmd==2:step+=hold
                    elif cmd==6:step+=2
                    elif cmd==7:step+=hold
                    self.peer.sendall(frame(seq,cmd,step))
                    if cmd==3:return
            except (EOFError,OSError,TimeoutError):pass
            except Exception as error:self.errors.append(error)
        def run():
            try:self.results.append(proxy.session(self.up,self.down,io_seconds=limits.get('io',1),stop_seconds=limits.get('stop',.6),wall_seconds=limits.get('wall',4),interrupted=limits.get('interrupted',lambda:False)))
            except Exception as error:self.errors.append(error)
        self.threads=[threading.Thread(target=peer),threading.Thread(target=run)]
        for t in self.threads:t.start()

    def command(self,cmd,seq,hold=0,speed=0):
        raw=proxy.REQUEST.pack(cmd,seq,0,speed,hold,0,4,0);self.client.sendall(raw)
        header=read(self.client,32);size,rgb,_,_=proxy.HEADER.unpack(header)
        return raw,header+read(self.client,size)+read(self.client,rgb)

    def finish(self):
        self.threads[1].join(timeout=4);self.assertFalse(self.threads[1].is_alive(),'proxy did not finish')
        self.assertFalse(self.errors,self.errors);self.assertEqual(len(self.results),1);return self.results[0]

    def test_normal_stream_is_byte_transparent_and_client_ack_distinct(self):
        self.start();reset,reply=self.command(1,1);self.assertEqual(reply,frame(1,1,100))
        drive,reply=self.command(2,2,10,200);self.assertEqual(reply,frame(2,2,110))
        stop,reply=self.command(3,3);self.assertEqual(reply,frame(3,3,110))
        result=self.finish();self.assertEqual(result['status'],'client_stop_acknowledged')
        self.assertFalse(result['stopAttempted']);self.assertTrue(result['stopAcknowledged']);self.assertEqual(result['stopCommandSource'],'client')
        self.assertEqual([proxy.REQUEST.pack(*r) for r in self.requests],[reset,drive,stop]);self.assertEqual(result['physicalStop'],'unverified')

    def test_client_eof_and_partial_upstream_get_fresh_stop_at_idle(self):
        for partial in (False,True):
            if partial:self.tearDown();self.setUp()
            with self.subTest(partial=partial):
                self.start();self.command(1,1);self.command(2,2,10,200)
                if partial:self.client.sendall(b'partial')
                self.client.close();result=self.finish()
                self.assertTrue(result['stopAttempted']);self.assertTrue(result['stopAcknowledged']);self.assertEqual(result['stopCommandSource'],'supervisor')
                self.assertEqual([r[:2] for r in self.requests],[(1,1),(2,2),(3,3)])

    def test_client_loss_during_completed_inflight_reply_stops_after_reply(self):
        entered=threading.Event();release=threading.Event()
        def handler(sock,request):
            if request[0]==2:
                entered.set();release.wait(2);sock.sendall(frame(request[1],2,110));return False
            return False
        # Handler itself sends drive response; the ordinary peer loop must not
        # send it again, so handle this case with a dedicated peer below.
        def peer():
            try:
                first=proxy.REQUEST.unpack(read(self.peer,64));self.requests.append(first);self.peer.sendall(frame(1,1,100))
                req=proxy.REQUEST.unpack(read(self.peer,64));self.requests.append(req);entered.set();release.wait(2);self.peer.sendall(frame(2,2,110))
                stop=proxy.REQUEST.unpack(read(self.peer,64));self.requests.append(stop);self.peer.sendall(frame(3,3,110))
            except (OSError,EOFError):pass
        def run():self.results.append(proxy.session(self.up,self.down,io_seconds=1,stop_seconds=.6,wall_seconds=4))
        self.threads=[threading.Thread(target=peer),threading.Thread(target=run)]
        for thread in self.threads:thread.start()
        self.command(1,1);self.client.sendall(proxy.REQUEST.pack(2,2,0,200,10,0,4,0));self.assertTrue(entered.wait(1));self.client.close();release.set()
        result=self.finish();self.assertTrue(result['stopAttempted']);self.assertTrue(result['stopAcknowledged'])
        self.assertEqual([r[:2] for r in self.requests],[(1,1),(2,2),(3,3)])

    def test_stalled_or_invalid_inflight_reply_never_guesses_stop(self):
        for mode in ('silent','wrong_sequence','stale_time'):
            if mode!='silent':self.tearDown();self.setUp()
            with self.subTest(mode=mode):
                def handler(sock,request):
                    if request[0]==2:
                        if mode=='silent':time.sleep(.6)
                        elif mode=='wrong_sequence':sock.sendall(frame(2,2,110,bad='wrong_sequence'))
                        else:
                            wire=frame(2,2,110);size,rgb,seq,reserved=proxy.HEADER.unpack(wire[:32]);body=wire[32:32+size].replace(b'"timeMs": 2200',b'"timeMs": 2000')
                            sock.sendall(proxy.HEADER.pack(len(body),rgb,seq,reserved)+body+wire[32+size:])
                        return True
                    return False
                self.start(handler,io=.25,stop=.2,wall=2);self.command(1,1)
                self.client.sendall(proxy.REQUEST.pack(2,2,0,200,10,0,4,0));result=self.finish()
                self.assertFalse(result['stopAttempted']);self.assertFalse(result['stopAcknowledged'])
                self.assertIn('in-flight exchange unverified',result['reason']);self.assertEqual([r[0] for r in self.requests],[1,2])

    def test_invalid_stop_ack_is_not_stop_confirmation(self):
        for mode in ('stop_drive','wrong_sequence','missing','duplicate','nonfinite','oversized'):
            if mode!='stop_drive':self.tearDown();self.setUp()
            def handler(sock,request):
                if request[0]!=3:return False
                if mode=='missing':time.sleep(.5);return True
                wire=frame(request[1],3,100,bad=mode)
                if mode in ('duplicate','nonfinite','oversized'):
                    size,rgb,seq,reserved=proxy.HEADER.unpack(wire[:32]);body=wire[32:32+size]
                    if mode=='duplicate':body=body.replace(b'"ack": 7',b'"ack": 6, "ack": 7')
                    elif mode=='nonfinite':body=body.replace(b'"ack": 7',b'"ack": NaN')
                    else:body=body.replace(b'"jointTicks": [1, 2, 3, 4]',b'"jointTicks": [9223372036854775808, 2, 3, 4]')
                    wire=proxy.HEADER.pack(len(body),rgb,seq,reserved)+body+wire[32+size:]
                sock.sendall(wire);return True
            with self.subTest(mode=mode):
                self.start(handler,stop=.2);self.command(1,1);self.client.close();result=self.finish()
                self.assertTrue(result['stopAttempted']);self.assertFalse(result['stopAcknowledged']);self.assertEqual(result['physicalStop'],'unverified')

    def test_partial_peer_write_never_guesses_next_sequence(self):
        original=proxy.write_all
        def partial(sock,data,deadline,stop):
            if sock is self.down and len(data)==64 and proxy.REQUEST.unpack(data)[0]==2:
                sock.send(data[:8]);raise OSError('injected partial peer write')
            return original(sock,data,deadline,stop)
        with mock.patch.object(proxy,'write_all',side_effect=partial):
            self.start();self.command(1,1);self.client.sendall(proxy.REQUEST.pack(2,2,0,200,10,0,4,0));result=self.finish()
        self.assertIn('in-flight exchange unverified',result['reason']);self.assertFalse(result['stopAttempted'])
        self.assertEqual([r[0] for r in self.requests],[1])

    def test_interrupt_at_boundary_or_in_flight(self):
        for inflight in (False,True):
            if inflight:self.tearDown();self.setUp()
            interrupted=threading.Event()
            def handler(sock,request):
                if inflight and request[0]==2:interrupted.set();time.sleep(.3);return True
                return False
            self.start(handler,interrupted=interrupted.is_set,io=.6,stop=.3,wall=3);self.command(1,1)
            if inflight:self.client.sendall(proxy.REQUEST.pack(2,2,0,200,10,0,4,0))
            else:interrupted.set();interrupted.set()
            result=self.finish()
            self.assertEqual(result['stopAttempted'],not inflight);self.assertEqual(result['stopAcknowledged'],not inflight)

    def test_invalid_upstream_request_can_stop_at_previous_boundary(self):
        self.start();self.command(1,1);self.client.sendall(proxy.REQUEST.pack(2,9,0,200,10,0,4,0))
        result=self.finish();self.assertTrue(result['stopAcknowledged']);self.assertEqual([r[:2] for r in self.requests],[(1,1),(3,2)])


if __name__=='__main__':unittest.main()

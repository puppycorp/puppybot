#!/usr/bin/env python3
"""Experimental bounded policy-stream witness; SHA-256 records only.

This standalone CPU-testable proxy is NOT integrated into the active policy
launcher. It sees complete messages on both sides of the socket, but a write
into a socket is not proof the child read it or executed a particular model.
It provides no OS exec/runtime identity or tamper-proof attestation.
"""
import argparse
import hashlib
import json
import os
import select
import signal
import socket
import sys
import time
from pathlib import Path

INPUT=(21168+7+128)*4
OUTPUT=(2+128)*4
STOP_REQUESTED=[]


def check_stop():
    if STOP_REQUESTED:raise InterruptedError(f'witness interrupted by signal {STOP_REQUESTED[0]}')


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def io_read(fd,size,timeout,allow_eof=False):
    data=bytearray();deadline=time.monotonic()+timeout
    while len(data)<size:
        check_stop()
        remaining=deadline-time.monotonic()
        if remaining<=0 or not select.select([fd],[],[],remaining)[0]:raise TimeoutError('policy stream read timeout')
        try:chunk=os.read(fd,size-len(data))
        except (InterruptedError,BlockingIOError):continue
        if not chunk:
            if not data and allow_eof:return None
            raise EOFError('partial policy stream frame')
        data.extend(chunk)
    return bytes(data)


def io_write(fd,data,timeout):
    remaining=memoryview(data);deadline=time.monotonic()+timeout
    while remaining:
        check_stop()
        left=deadline-time.monotonic()
        if left<=0 or not select.select([],[fd],[],left)[1]:raise TimeoutError('policy stream write timeout')
        try:n=os.write(fd,remaining)
        except (InterruptedError,BlockingIOError):continue
        if n<=0:raise EOFError('closed policy stream')
        remaining=remaining[n:]


def child_start(binary,weights,weights_sha,kernels,child_fd,owner):
    # Linux parent-death signal bounds the direct child if this proxy dies.
    import ctypes
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(1,signal.SIGKILL,0,0,0)!=0 or os.getppid()!=owner:os._exit(125)
    try:
        os.dup2(child_fd,3,inheritable=True)
        for name in os.listdir('/proc/self/fd'):
            try:fd=int(name)
            except ValueError:continue
            if fd>=4:
                try:os.close(fd)
                except OSError:pass
        os.execve(binary,[binary,weights,weights_sha,kernels,'3'],os.environ.copy())
    except BaseException:os._exit(127)


def wait_child(pid,timeout):
    deadline=time.monotonic()+timeout
    while True:
        check_stop()
        done,status=os.waitpid(pid,os.WNOHANG)
        if done:return status
        if time.monotonic()>=deadline:raise TimeoutError('policy child exit timeout')
        time.sleep(.01)


def run(control_fd,policy,policy_sha,weights,weights_sha,kernels,receipt,journal,timeout):
    STOP_REQUESTED.clear()
    if not 0.1<=timeout<=60 or control_fd<3:raise ValueError('invalid descriptor or timeout')
    policy=Path(policy);weights=Path(weights);kernels=Path(kernels);receipt=Path(receipt);journal=Path(journal)
    if not all(p.is_absolute() for p in (policy,weights,kernels,receipt,journal)):raise ValueError('paths must be absolute')
    if sha(policy)!=policy_sha or sha(weights)!=weights_sha or not kernels.is_dir():raise ValueError('policy/weights hash or kernels invalid')
    # Explicit hashes pin the kernel files present at launch and after exit;
    # they do not attest which libraries or kernels the child actually loaded.
    kernel_paths=sorted(kernels.iterdir())
    if len(kernel_paths)<5 or any(not p.is_file() for p in kernel_paths):raise ValueError('invalid kernel directory')
    before={p.name:sha(p) for p in kernel_paths}
    receipt_sha=sha(receipt); witness_sha=sha(Path(__file__).resolve()); declaration=json.loads(receipt.read_text())
    if declaration.get('binarySHA256')!=policy_sha or declaration.get('weightsSHA256')!=weights_sha or declaration.get('kernels')!=before:
        raise ValueError('policy receipt does not match pinned files')
    os.set_blocking(control_fd,False)
    descriptor=os.open(journal,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC,0o600)
    child_pid=None; child_status=None; channel=None; parent=None
    def event(value):
        data=(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode();at=0
        while at<len(data):
            n=os.write(descriptor,data[at:])
            if n<=0:raise OSError('cannot write witness journal')
            at+=n
    old_handlers={}
    def interrupted(signum,_frame):STOP_REQUESTED.append(signum)
    try:
        for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):old_handlers[sig]=signal.signal(sig,interrupted)
        event({'schema':'puppybot.policy-stream-witness.v1','policySHA256':policy_sha,'weightsSHA256':weights_sha,
               'kernelSHA256':before,'receiptSHA256':receipt_sha,'witnessSHA256':witness_sha,'inputBytes':INPUT,'outputBytes':OUTPUT,
               'scope':'proxy-observed socket bytes; child receipt, executable/runtime identity and inference correctness not independently proven'})
        check_stop()
        parent,channel=socket.socketpair();owner=os.getpid();child_pid=os.fork()
        if child_pid==0:
            parent.close();child_start(str(policy),str(weights),weights_sha,str(kernels),channel.fileno(),owner)
        channel.close();channel=parent;channel.setblocking(False);check_stop()
        magic=io_read(channel.fileno(),8,timeout)
        if magic!=b'VCPOL001':raise ValueError('unexpected policy handshake')
        io_write(control_fd,magic,timeout);count=0
        while True:
            data=io_read(control_fd,INPUT,timeout,allow_eof=True)
            if data is None:break
            if count>=512:raise ValueError('too many policy frames')
            io_write(channel.fileno(),data,timeout);answer=io_read(channel.fileno(),OUTPUT,timeout)
            io_write(control_fd,answer,timeout)
            event({'sequence':count,'inputSHA256':hashlib.sha256(data).hexdigest(),'outputSHA256':hashlib.sha256(answer).hexdigest()})
            count+=1
        if not count:raise ValueError('empty policy stream')
        channel.shutdown(socket.SHUT_WR)
        # No second response is permitted after the controller has closed.
        if io_read(channel.fileno(),1,timeout,allow_eof=True) is not None:raise ValueError('extra policy output')
        child_status=wait_child(child_pid,timeout);child_pid=None
        if child_status!=0:raise ValueError('policy process exited unsuccessfully')
        after_paths=sorted(kernels.iterdir())
        if (sha(policy)!=policy_sha or sha(weights)!=weights_sha or sha(receipt)!=receipt_sha or sha(Path(__file__).resolve())!=witness_sha
                or any(not p.is_file() for p in after_paths) or {p.name:sha(p) for p in after_paths}!=before):
            raise ValueError('policy inputs changed during observation')
        check_stop();event({'footer':'complete','frames':count,'policyExit':0});os.fsync(descriptor);check_stop()
    finally:
        if channel is not None:channel.close()
        if parent is not None and parent is not channel:parent.close()
        if child_pid is not None:
            try:os.kill(child_pid,signal.SIGKILL)
            except ProcessLookupError:pass
            try:os.waitpid(child_pid,0)
            except ChildProcessError:pass
        os.close(descriptor)
        for sig,handler in old_handlers.items():signal.signal(sig,handler)
    check_stop()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ('policy','policy-sha256','weights','weights-sha256','kernels','receipt','journal'):parser.add_argument('--'+arg,required=True)
    parser.add_argument('--fd',required=True,type=int);parser.add_argument('--timeout',type=float,default=10)
    args=parser.parse_args()
    run(args.fd,args.policy,args.policy_sha256,args.weights,args.weights_sha256,args.kernels,args.receipt,args.journal,args.timeout)


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,EOFError,TimeoutError) as error:raise SystemExit(f'Policy witness failed: {error}')

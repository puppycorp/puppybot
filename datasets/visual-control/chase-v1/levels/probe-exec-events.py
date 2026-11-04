#!/usr/bin/env python3
"""Bounded Linux ptrace experiment; output is diagnostic, not attestation."""
import base64
import ctypes
import json
import os
import signal
import sys
import time

LIBC = ctypes.CDLL(None, use_errno=True)
LIBC.ptrace.restype = ctypes.c_long
TRACEME, CONT, SETOPTIONS, GETEVENTMSG = 0, 7, 0x4200, 0x4201
OPTIONS = 0x2 | 0x4 | 0x8 | 0x10 | 0x100000  # fork, vfork, clone, exec, exitkill
WALL = 0x40000000


def ptrace(request, pid, data=0):
    ctypes.set_errno(0)
    result = LIBC.ptrace(ctypes.c_uint(request), ctypes.c_int(pid), ctypes.c_void_p(), ctypes.c_void_p(data))
    if result == -1 and ctypes.get_errno():
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return result


def trace(argv, timeout=5, max_events=128):
    raise RuntimeError('probe disabled: pending fork-event cleanup race')


def _unreviewed_trace(argv, timeout=5, max_events=128):
    if not argv or timeout <= 0 or max_events <= 0:
        raise ValueError('invalid probe limits or command')
    interrupted = []
    def on_signal(signum, _frame):
        interrupted.append(signum)
    previous = {sig: signal.signal(sig, on_signal) for sig in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
    try:
        pid = os.fork()
    except BaseException:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        raise
    if pid == 0:
        try:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            ptrace(TRACEME, 0)
            os.kill(os.getpid(), signal.SIGSTOP)
            os.execve(argv[0], argv, os.environb.copy())
        except OSError as exc:
            os.write(2, f'probe child setup/exec failed: {exc}\n'.encode())
            os._exit(127)
        except BaseException:
            os._exit(127)
    live = {pid}
    events = []
    deadline = time.monotonic() + timeout
    initial = True
    attached = set()
    try:
        while live:
            if interrupted:
                raise RuntimeError(f'probe interrupted by signal {interrupted[0]}')
            if time.monotonic() >= deadline:
                raise TimeoutError('ptrace probe deadline exceeded')
            child = 0
            for tracked in tuple(live):
                try:
                    child, status = os.waitpid(tracked, WALL | os.WNOHANG)
                except ChildProcessError:
                    raise RuntimeError(f'traced process {tracked} disappeared before exit')
                if child:
                    break
            if child == 0:
                time.sleep(.005)
                continue
            if os.WIFEXITED(status) or os.WIFSIGNALED(status):
                live.discard(child)
                if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
                    raise RuntimeError(f'traced command {child} failed (or ptrace setup was denied)')
                continue
            if not os.WIFSTOPPED(status):
                raise RuntimeError('unexpected wait status')
            sig = os.WSTOPSIG(status)
            event = status >> 16
            deliver = sig
            if initial:
                if child != pid or sig != signal.SIGSTOP or event:
                    raise RuntimeError('ptrace setup failed before initial stop')
                ptrace(SETOPTIONS, child, OPTIONS)
                initial = False
                deliver = 0
            elif event in (1, 2, 3):
                new_pid = ctypes.c_ulong()
                ptrace(GETEVENTMSG, child, ctypes.addressof(new_pid))
                live.add(new_pid.value)
                attached.add(new_pid.value)
                if event == 3:
                    raise RuntimeError('clone/thread tracing is unsupported')
                if len(live) > max_events:
                    raise RuntimeError('ptrace process limit exceeded')
                deliver = 0
            elif event == 4:
                with open(f'/proc/{child}/cmdline', 'rb') as cmdline:
                    raw = cmdline.read()
                if not raw.endswith(b'\0'):
                    raise RuntimeError('missing or malformed cmdline at exec stop')
                args = raw[:-1].split(b'\0')
                events.append({'pid': child, 'argvBase64': [base64.b64encode(a).decode('ascii') for a in args],
                               'exeBase64': base64.b64encode(os.readlink(os.fsencode(f'/proc/{child}/exe'))).decode('ascii')})
                if len(events) > max_events:
                    raise RuntimeError('ptrace event limit exceeded')
                deliver = 0
            elif event:
                raise RuntimeError(f'unexpected ptrace event {event}')
            elif child in attached and sig == signal.SIGSTOP:
                attached.remove(child)
                deliver = 0
            ptrace(CONT, child, deliver)
        if initial or not events:
            raise RuntimeError('no exec event observed')
        return {'status': 'diagnostic_only', 'execEvents': events}
    finally:
        for child in live:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for child in live:
            while True:
                try:
                    _, status = os.waitpid(child, WALL)
                    if os.WIFEXITED(status) or os.WIFSIGNALED(status):
                        break
                    os.kill(child, signal.SIGKILL)
                except ChildProcessError:
                    break
                except ProcessLookupError:
                    break
                except InterruptedError:
                    continue
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main():
    if len(sys.argv) < 2:
        raise ValueError('usage: probe-exec-events.py COMMAND [ARG ...]')
    print(json.dumps(trace([os.fsencode(arg) for arg in sys.argv[1:]]), sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}), file=sys.stderr)
        sys.exit(1)

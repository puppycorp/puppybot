#!/usr/bin/env python3
"""Lock-holding subreaper and continuous resource guard for the paired pilot."""
import ctypes
import fcntl
import json
import os
import select
import signal
import subprocess
import time
from pathlib import Path

GIB = 1024**3


def children(parent):
    result = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            text = (entry / 'stat').read_text(); fields = text[text.rfind(')') + 2:].split()
            if int(fields[1]) == parent:
                result.append((int(entry.name), fields[0]))
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError, IndexError):
            continue
    return result


def descendants():
    pending = [os.getpid()]; result = {}; seen = set(pending)
    while pending:
        for pid, state in children(pending.pop()):
            if pid not in seen:
                seen.add(pid); pending.append(pid); result[pid] = state
    return result


def send(pids, sig):
    for pid, state in pids.items():
        if state == 'Z':
            continue
        try:
            fd = os.pidfd_open(pid)
            try: signal.pidfd_send_signal(fd, sig)
            finally: os.close(fd)
        except OSError:
            pass


def reap():
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if not pid: return
        except ChildProcessError:
            return


def run(output, lock_path, command, env, parent_pid, read_resources, interval=1.0, grace=2.0, wall_seconds=4200):
    """Hold lock until every descendant exits, even after parent/coordinator death."""
    output = Path(output); lock_path = Path(lock_path)
    if os.getppid() != parent_pid:
        raise RuntimeError('guardian parent already exited')
    parent_fd = os.pidfd_open(parent_pid); parent_poll = select.poll(); parent_poll.register(parent_fd, select.POLLIN)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        os.close(parent_fd); raise OSError(ctypes.get_errno(), 'cannot establish subreaper')
    signals = []
    def interrupted(sig, _frame): signals.append(sig)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP): signal.signal(sig, interrupted)
    process = None; reason = None; cleaned = False; emergency = False; samples = 0; observed_done = None
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if parent_poll.poll(0):
            raise RuntimeError('guardian parent exited before start')
        child_env = dict(env, PUPPY_TURN_GUARD_PID=str(os.getpid()), PUPPY_TURN_GUARD_FD=str(lock.fileno()),
                         PUPPY_TURN_GUARD_OUTPUT=str(output))
        with (output / 'guardian-telemetry.jsonl').open('x') as log, (output / 'guardian-client.log').open('x') as client:
            started_at = time.monotonic()
            process = subprocess.Popen(command, cwd=output, env=child_env, stdout=client, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            def sample(phase):
                nonlocal samples, emergency
                try:
                    row = read_resources(); row.update({'phase': phase, 'monotonicSeconds': time.monotonic()})
                    if (type(row.get('freeBytes')) is not int or type(row.get('gpuFreeBytes')) is not int or
                            type(row.get('baselinePassed')) is not bool or
                            row['freeBytes'] < 0 or row['gpuFreeBytes'] < 0):
                        raise ValueError('invalid resource sample')
                    emergency = emergency or row['freeBytes'] < 32 * GIB
                    log.write(json.dumps(row, sort_keys=True) + '\n'); log.flush(); samples += 1
                    return row
                except Exception as error:
                    emergency = True
                    return {'error': str(error), 'freeBytes': 0, 'gpuFreeBytes': 0}

            try:
                (output / 'guardian-launch.json').write_text(json.dumps({'coordinatorPID': process.pid,
                    'guardianPID': os.getpid(), 'parentPID': parent_pid, 'command': command,
                    'environment': child_env, 'startedMonotonic': started_at, 'wallSeconds': wall_seconds},
                    sort_keys=True, indent=2) + '\n')
                while True:
                    row = sample('active')
                    floor = 34 if row.get('baselinePassed') is True else 38
                    if row['freeBytes'] < floor * GIB or row['gpuFreeBytes'] < 2 * GIB:
                        reason = row.get('error') or 'active GPU or disk floor breached'
                    if parent_poll.poll(0): reason = reason or 'parent exited'
                    if signals: reason = reason or 'guardian interrupted'
                    if time.monotonic() - started_at >= wall_seconds: reason = reason or 'guardian deadline exceeded'
                    code = process.poll()
                    if code is not None and code != 0: reason = reason or 'coordinator failed'
                    if reason or code is not None:
                        observed_done = time.monotonic(); break
                    time.sleep(interval)
            except BaseException as error:
                reason = reason or f'guardian exception: {error}'
                observed_done = time.monotonic()
            finally:
                # Never abandon the lock while an inherited or escaped child lives.
                started = time.monotonic(); empty = 0
                while True:
                    row = sample('cleanup')
                    if row['freeBytes'] < 34 * GIB or row['gpuFreeBytes'] < 2 * GIB:
                        reason = reason or row.get('error') or 'cleanup GPU or disk floor breached'
                    if parent_poll.poll(0): reason = reason or 'parent exited'
                    if signals: reason = reason or 'guardian interrupted'
                    process.poll()
                    try:
                        if process.returncode is not None: reap()
                        alive = descendants()
                    except OSError:
                        # Losing process visibility must not release the lock.
                        reason = reason or 'cannot verify descendant cleanup'
                        emergency = True
                        if process.returncode is None: send({process.pid: 'S'}, signal.SIGKILL)
                        time.sleep(min(interval, 0.1)); continue
                    if alive:
                        cleaned = True; empty = 0
                        sig = signal.SIGKILL if emergency or time.monotonic() - started >= grace else signal.SIGTERM
                        send(alive, sig)
                    else:
                        empty += 1
                        if empty >= 2: break
                    time.sleep(min(interval, 0.1))
                if cleaned: reason = reason or 'leftover descendants required cleanup'
                result = {'status': 'passed' if reason is None and process.returncode == 0 else 'failed',
                          'reason': reason, 'coordinatorExit': process.returncode, 'descendantsTerminated': cleaned,
                          'diskEmergency': emergency, 'samples': samples,
                          'observedDoneMonotonic': observed_done, 'endedMonotonic': time.monotonic(),
                          'scope': 'local resource sampling and descendant cleanup; not physical safety'}
                (output / 'guardian-result.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    os.close(parent_fd)
    return result


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and resource scheduling.')

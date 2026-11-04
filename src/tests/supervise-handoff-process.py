#!/usr/bin/env python3
"""Observe the handoff process tree using the expected file's mmap identity.

Usage: supervise-handoff-process.py NEW_OUTPUT -- COMMAND [ARG ...]

This is an isolated diagnostic variant of supervise-selection.py, not an
attestation or selection verifier.
Polling /proc can miss short-lived descendants and cannot prove that no
unobserved work used a holdout. It never enables the held-out runner.
"""
import hashlib
import ctypes
import json
import mmap
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
HIP = (PROJECT / 'build/flex/rocm-runtime/libamdhip64.so').resolve()
ENV_KEYS = ('HOME', 'LANG', 'LC_ALL', 'LD_LIBRARY_PATH', 'PATH', 'TMPDIR',
            'PUPPYBOT_PROJECT', 'PUPPYBOT_CHASE_HORIZON', 'PUPPYBOT_CHASE_FULL',
            'PUPPYBOT_EVAL_SELECTION', 'PUPPYBOT_EVAL_SELECTION_SEED',
            'PUPPYBOT_EVAL_TWO_ROOM', 'PUPPYBOT_CHASE_PARTS', 'SDL_VIDEODRIVER')


class ProcessRace(Exception):
    """The process changed while sampling; no single observation is valid."""


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def stat_process(pid):
    proc = Path('/proc') / str(pid)
    raw = (proc / 'stat').read_text()
    fields = raw[raw.rfind(')') + 2:].split()
    if len(fields) < 20:
        raise ValueError(f'invalid process stat: {pid}')
    return {'pid': pid, 'state': fields[0], 'ppid': int(fields[1]), 'starttime': int(fields[19])}


def children(pid):
    path = Path('/proc') / str(pid) / 'task' / str(pid) / 'children'
    return [int(value) for value in path.read_text().split()]


def read_env(path):
    result = {}
    for entry in path.read_bytes().split(b'\0'):
        if b'=' not in entry:
            continue
        key, value = entry.split(b'=', 1)
        name = os.fsdecode(key)
        if name in ENV_KEYS:
            result[name] = os.fsdecode(value)
    return result


def mapping_identity(path):
    # On Btrfs subvolumes stat.st_dev can be a different device number from
    # the VMA's backing filesystem device. Derive the latter from an actual
    # mapping of the opened file, rather than comparing different namespaces.
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        signature = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if before.st_size < mmap.PAGESIZE:
            raise ValueError('HIP file too small for identity mapping')
        with mmap.mmap(stream.fileno(), mmap.PAGESIZE, access=mmap.ACCESS_COPY) as view:
            address = ctypes.addressof(ctypes.c_char.from_buffer(view))
            matches = []
            for line in Path('/proc/self/maps').read_text().splitlines():
                fields = line.split(maxsplit=5)
                begin, end = (int(x, 16) for x in fields[0].split('-'))
                if begin <= address < end:
                    if len(fields) != 6 or fields[5].endswith(' (deleted)') or int(fields[2], 16) != 0:
                        raise ValueError('invalid or deleted expected HIP identity mapping')
                    matches.append((tuple(int(x, 16) for x in fields[3].split(':')), int(fields[4])))
            if len(matches) != 1 or matches[0][1] != before.st_ino:
                raise ValueError('cannot bind expected HIP mapping to opened inode')
        after = os.fstat(stream.fileno()); current = path.stat()
        if any((s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns) != signature for s in (after, current)):
            raise ValueError('expected HIP file changed while mapping')
        return matches[0], signature


def hip_maps(path, expected, expected_stat):
    found = []
    for line in path.read_text(errors='strict').splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) != 6 or 'libamdhip64.so' not in fields[5]:
            continue
        name = fields[5]
        if name.endswith(' (deleted)'):
            raise ValueError(f'deleted HIP mapping: {name}')
        mapped = Path(name)
        device = tuple(int(value, 16) for value in fields[3].split(':'))
        inode = int(fields[4])
        if (device, inode) != expected:
            raise ValueError(f'unexpected HIP mapping: {name} device={device} inode={inode}')
        # Different Btrfs subvolumes can expose the same backing device and
        # inode in maps. Also verify the visible file's own stat identity.
        with mapped.open('rb') as stream:
            current = os.fstat(stream.fileno())
            signature = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
            if signature != expected_stat:
                raise ValueError(f'unexpected HIP file identity: {name}')
        found.append({'path': name, 'device': list(device), 'inode': inode})
    return found


def observe(pid, hip_identity, executable_cache, hip_stat_identity):
    proc = Path('/proc') / str(pid)
    before = stat_process(pid)
    if before['state'] == 'Z':
        return before, None
    exe = os.readlink(proc / 'exe')
    cwd = os.readlink(proc / 'cwd')
    if exe.endswith(' (deleted)'):
        raise ValueError(f'deleted executable: {exe}')
    with (proc / 'exe').open('rb') as executable:
        executable_stat = os.fstat(executable.fileno())
        identity = (executable_stat.st_dev, executable_stat.st_ino, executable_stat.st_size, executable_stat.st_mtime_ns)
        executable_sha = executable_cache.get(identity)
        if executable_sha is None:
            executable_digest = hashlib.sha256()
            for block in iter(lambda: executable.read(1024 * 1024), b''):
                executable_digest.update(block)
            executable_sha = executable_digest.hexdigest()
        after_read = os.fstat(executable.fileno())
        if (after_read.st_dev, after_read.st_ino, after_read.st_size, after_read.st_mtime_ns) != identity:
            raise ProcessRace(f'executable changed while hashing: {pid}')
        executable_cache[identity] = executable_sha
    argv = [os.fsdecode(value) for value in (proc / 'cmdline').read_bytes().split(b'\0') if value]
    env = read_env(proc / 'environ')
    maps = hip_maps(proc / 'maps', hip_identity, hip_stat_identity)
    after = stat_process(pid)
    current_executable = os.stat(proc / 'exe')
    current_argv = [os.fsdecode(value) for value in (proc / 'cmdline').read_bytes().split(b'\0') if value]
    if (after['starttime'] != before['starttime'] or os.readlink(proc / 'exe') != exe
            or (current_executable.st_dev, current_executable.st_ino, current_executable.st_size, current_executable.st_mtime_ns) != identity
            or os.readlink(proc / 'cwd') != cwd or read_env(proc / 'environ') != env or current_argv != argv):
        raise ProcessRace(f'process changed while reading: {pid}')
    return before, {'executable': exe, 'executableSHA256': executable_sha,
                    'executableDevice': [os.major(executable_stat.st_dev), os.minor(executable_stat.st_dev)],
                    'executableInode': executable_stat.st_ino, 'argv': argv, 'cwd': cwd,
                    'initialEnvironment': env, 'hipMappings': maps}


def tree(root):
    pending, seen = [root], set()
    while pending:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        try:
            pending.extend(children(pid))
        except FileNotFoundError:
            continue
    return seen


def cleanup_children():
    # Work only from this supervisor's current child tree. Recheck parentage
    # before signalling, and use pidfds so a recycled PID is not signalled.
    seen, problems = set(), set()
    for sig, seconds in ((signal.SIGTERM, 2), (signal.SIGKILL, 3)):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            pending, live = [os.getpid()], []
            while pending:
                parent = pending.pop()
                try:
                    pids = children(parent)
                except FileNotFoundError:
                    continue
                except OSError as error:
                    problems.add(f'cannot list children of {parent}: {error}')
                    continue
                for pid in pids:
                    try:
                        state = stat_process(pid)
                        if state['ppid'] != parent or state['state'] == 'Z':
                            continue
                        pending.append(pid)
                        fd = os.pidfd_open(pid)
                        try:
                            check = stat_process(pid)
                            if check['ppid'] == parent and check['starttime'] == state['starttime']:
                                signal.pidfd_send_signal(fd, sig)
                                live.append(pid)
                                seen.add(pid)
                        finally:
                            os.close(fd)
                    except (ProcessLookupError, FileNotFoundError):
                        pass
                    except OSError as error:
                        problems.add(f'cannot signal or inspect child {pid}: {error}')
            while True:
                try:
                    if not os.waitpid(-1, os.WNOHANG)[0]:
                        break
                except ChildProcessError:
                    break
            if not live:
                break
            time.sleep(0.05)
    try:
        remaining = sorted(tree(os.getpid()) - {os.getpid()})
    except OSError as error:
        problems.add(f'cannot verify child cleanup: {error}')
        remaining = []
    return sorted(seen), remaining, sorted(problems)


def stop_group(pid, sig):
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass


def main():
    if len(sys.argv) < 4 or sys.argv[2] != '--':
        raise SystemExit(__doc__)
    output = Path(sys.argv[1]).resolve()
    if output.exists():
        raise ValueError(f'output already exists: {output}')
    if not HIP.is_file():
        raise ValueError(f'missing HIP runtime: {HIP}')
    command = sys.argv[3:]
    if not command:
        raise ValueError('missing command')
    identity, stat_identity = mapping_identity(HIP)
    runtime_sha = sha(HIP)
    if mapping_identity(HIP) != (identity, stat_identity):
        raise ValueError('HIP file changed while hashing')
    env = {'HOME': os.environ.get('HOME', str(PROJECT)), 'LANG': 'C', 'LC_ALL': 'C',
           'PATH': '/usr/bin:/bin', 'LD_LIBRARY_PATH': str(HIP.parent),
           'PUPPYBOT_PROJECT': str(PROJECT), 'PUPPYBOT_CHASE_HORIZON': '300',
           'PUPPYBOT_CHASE_FULL': '0'}
    if 'TMPDIR' in os.environ:
        env['TMPDIR'] = os.environ['TMPDIR']
    output.mkdir(parents=True, mode=0o700)
    events_path = output / 'observations.jsonl'
    log_path = output / 'runner.log'
    events_fd = os.open(events_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    events = os.fdopen(events_fd, 'w', buffering=1)
    log = os.fdopen(log_fd, 'w')
    def emit(row):
        events.write(json.dumps(row, sort_keys=True) + '\n')
    emit({'event': 'start', 'command': command, 'sanitizedEnvironment': env,
          'hipFile': str(HIP), 'hipSHA256': runtime_sha, 'hipDevice': identity[0], 'hipInode': identity[1],
          'hipStatDevice': [os.major(stat_identity[0]), os.minor(stat_identity[0])]})
    # Reparent orphaned descendants so the monitor can identify survivors.
    libc = ctypes.CDLL(None, use_errno=True)
    previous_subreaper = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(previous_subreaper), 0, 0, 0) != 0:  # PR_GET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), 'cannot read child subreaper state')
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), 'cannot enable child subreaper')
    process = None
    seen, policy_seen, policy_hip, errors, executable_cache, stop_requested = {}, set(), set(), [], {}, []
    deadline = time.monotonic() + 7200
    def interrupted(signum, frame):
        stop_requested.append(signum)
    handlers = {}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            handlers[sig] = signal.signal(sig, interrupted)
        if stop_requested:
            errors.append(f'supervisor received signal {stop_requested[0]} before launch')
        else:
            process = subprocess.Popen(command, cwd=PROJECT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        while process is not None and process.poll() is None:
            if stop_requested:
                errors.append(f'supervisor received signal {stop_requested[0]}')
                stop_group(process.pid, signal.SIGTERM)
                break
            if time.monotonic() >= deadline:
                errors.append('two-hour supervisor wall deadline exceeded')
                stop_group(process.pid, signal.SIGTERM)
                break
            # Include workers orphaned by intermediate children and adopted
            # by this subreaper while the runner is still alive.
            for pid in tree(os.getpid()) - {os.getpid()}:
                try:
                    state, observed = observe(pid, identity, executable_cache, stat_identity)
                    key = (pid, state['starttime'])
                    if observed is None:
                        continue
                    signature = (observed['executable'], observed['executableSHA256'], observed['executableInode'],
                                 observed['cwd'], tuple(observed['argv']), json.dumps(observed['initialEnvironment'], sort_keys=True))
                    if seen.get(key) != signature:
                        emit({'event': 'process', **state, **observed})
                        seen[key] = signature
                    if Path(observed['executable']).name == 'policy':
                        policy_seen.add(key)
                        if observed['hipMappings'] and key not in policy_hip:
                            emit({'event': 'policyExpectedHipFileMappingObserved', **state, 'mappings': observed['hipMappings']})
                            policy_hip.add(key)
                except (FileNotFoundError, ProcessRace):
                    # A short-lived child may disappear between /proc reads.
                    emit({'event': 'sampleRace', 'pid': pid})
                except (OSError, ValueError) as error:
                    errors.append(str(error))
                    emit({'event': 'error', 'pid': pid, 'message': str(error)})
                    stop_group(process.pid, signal.SIGTERM)
                    process.wait(timeout=10)
                    break
            time.sleep(0.05)
    except OSError as error:
        errors.append(f'cannot launch or observe runner: {error}')
    finally:
        # Handlers stay installed throughout cleanup: repeated signals set a
        # flag rather than interrupting termination/reaping halfway through.
        if process is not None and process.poll() is None:
            stop_group(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                stop_group(process.pid, signal.SIGKILL)
                process.wait()
        cleaned, survivors, cleanup_errors = cleanup_children()
        if cleaned or survivors:
            errors.append(f'runner left adopted children: cleaned={cleaned}, remaining={survivors}')
        errors.extend(cleanup_errors)
        if libc.prctl(36, previous_subreaper.value, 0, 0, 0) != 0:
            errors.append(f'cannot restore child subreaper state: errno {ctypes.get_errno()}')
        try:
            hip_unchanged = HIP.is_file() and sha(HIP) == runtime_sha and mapping_identity(HIP) == (identity, stat_identity)
        except (OSError, ValueError):
            hip_unchanged = False
        if stop_requested and not any('supervisor received signal' in error for error in errors):
            errors.append(f'supervisor received signal {stop_requested[0]} during launch or cleanup')
        result = {'event': 'end', 'exitCode': process.returncode if process is not None else None, 'observedProcesses': len(seen),
                  'observedPolicies': len(policy_seen), 'policiesWithExpectedHipFileMapping': len(policy_hip),
                  'hipFileUnchanged': hip_unchanged, 'errors': errors,
                  'status': 'diagnostic_only', 'eligibleForQualification': False,
                  'limitations': ['polling may miss short-lived or escaped descendants',
                                  'mapped inode and current disk hash do not prove loaded bytes or all runtime dependencies',
                                  'an mmap of the expected HIP file does not establish library initialization or GPU execution',
                                  'executable hashes are cached by device, inode, size and modification time',
                                  'proc environ describes the process initial environment, not later setenv calls',
                                  'does not prove prior model ancestry, actor inputs, or no unmonitored runs']}
        emit(result)
        events.close()
        log.close()
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    print(json.dumps(result, sort_keys=True))
    if process is None or process.returncode or errors or not hip_unchanged or not policy_seen or policy_seen != policy_hip:
        return 1
    # /proc polling has no complete fork/exec coverage. Refuse to act as a
    # qualification gate even when all observed policy processes mapped HIP.
    return 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f'selection supervisor: {error}')

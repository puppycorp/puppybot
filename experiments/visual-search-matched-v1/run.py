#!/usr/bin/env python3
"""Use the established matched search runner with opt-in visual transfer."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


base = load('visual_matched_base_runner', ROOT / 'experiments/physical-search-fallback-trial-v1/run.py')
builder = load('visual_matched_builder', HERE / 'build.py')
base.__file__ = str(HERE / 'run.py')
original_required = base.required


def env_for(flag):
    return dict(PATH='/usr/bin:/bin', HOME=str(Path.home()), SDL_VIDEODRIVER='offscreen',
                LD_LIBRARY_PATH=str(ROOT / 'build/flex/rocm-runtime'),
                PUPPYBOT_PHYSICAL_NAV_LIMIT='90', PUPPYBOT_PHYSICAL_POLL_LIMIT='1499',
                PUPPYBOT_PHYSICAL_SEARCH_FALLBACK='1', PUPPYBOT_VISUAL_SEARCH_RECOVERY=flag)


def required(root, build):
    paths = original_required(root, build)
    paths += [Path(__file__), HERE / 'audit.py', HERE / 'monitor.py', HERE / 'build.py',
              ROOT / 'experiments/visual-search-recovery-v1/transform.py',
              ROOT / 'experiments/visual-search-recovery-v1/audit.py',
              ROOT / 'experiments/visual-exact-stall-v1/visual-stall.flex',
              ROOT / 'experiments/physical-search-fallback-trial-v1/run.py',
              ROOT / 'experiments/physical-search-fallback-trial-v1/audit.py',
              builder.ARCHIVE / 'build.json', builder.ARCHIVE / 'client',
              builder.ARCHIVE / 'simulator', builder.COMPILER]
    return paths


base.check_build = builder.verify
base.env_for = env_for
base.required = required
ARMS = base.ARMS
sha = base.sha
hidden = base.hidden
check_build = base.check_build
check_manifest = base.check_manifest
check_invocation = base.check_invocation
launch = base.launch


if __name__ == '__main__': raise SystemExit('Disabled pending independent review and monitored scheduling.')

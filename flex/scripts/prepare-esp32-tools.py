#!/usr/bin/env python3
"""Download pinned Espressif build tools into ignored build/; no installation."""
import argparse
import hashlib
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]/'build/flex/esp32/tools'
TOOLS = {
    'xtensa': ('https://github.com/espressif/crosstool-NG/releases/download/esp-14.2.0_20241119/'
               'xtensa-esp-elf-14.2.0_20241119-x86_64-linux-gnu.tar.xz',
               'e3e6dcf3d275c3c9ab0e4c8a9d93fd10e7efc035d435460576c9d95b4140c676'),
    'qemu': ('https://github.com/espressif/qemu/releases/download/esp-develop-9.2.2-20260417/'
             'qemu-xtensa-softmmu-esp_develop_9.2.2_20260417-x86_64-linux-gnu.tar.xz',
             '0eecb2a34a5586c0e59110f77b9343b7b336e82fdb0e1a30e1dc1bab8a547e35'),
}


def download(name):
    url, expected = TOOLS[name]
    archive = ROOT/url.rsplit('/', 1)[1]
    if not archive.exists():
        temporary = archive.with_suffix('.download')
        urllib.request.urlretrieve(url, temporary)
        assert hashlib.sha256(temporary.read_bytes()).hexdigest() == expected
        temporary.replace(archive)
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
    with tarfile.open(archive) as package:
        members = package.getmembers()
        if name == 'xtensa':
            members = [member for member in members if '/lib/' in member.name and '.so' in member.name
                       or member.name.endswith(('/xtensa-esp32-elf-ld', '/xtensa-esp-elf-ld'))]
        package.extractall(ROOT, members=members, filter='data')
    print(f'Verified {name}: {ROOT}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', action='store_true')
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    download('xtensa')
    if args.qemu:
        download('qemu')

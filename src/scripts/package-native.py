#!/usr/bin/env python3
"""Package the built native runtime and inspected ESP32 image for release."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def package(name, files, instructions):
    output = ROOT / 'artifacts' / name
    output.parent.mkdir(exist_ok=True)
    # Validate every input before publishing an archive.
    hashes = {}
    for target, source in files.items():
        if not source.is_file() or source.is_symlink():
            raise ValueError(f'missing or linked release input: {source}')
        hashes[target] = hashlib.sha256(source.read_bytes()).hexdigest()
    temporary = output.with_suffix('.tmp.zip')
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for target, source in files.items():
                archive.write(source, target)
            archive.writestr('SHA256SUMS', ''.join(f'{digest}  {path}\n' for path, digest in hashes.items()))
            archive.writestr('README.txt', instructions)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError('release archive failed CRC verification')
            for path, digest in hashes.items():
                if hashlib.sha256(archive.read(path)).hexdigest() != digest:
                    raise ValueError(f'release archive hash mismatch: {path}')
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({'artifact': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}))


def main():
    build = ROOT / 'build/flex'
    firmware = build / 'esp32'
    subprocess.run([sys.executable, str(ROOT / 'src/scripts/inspect-esp32.py'),
                    str(firmware / 'puppybot.elf'), str(firmware / 'puppybot.bin')], check=True)
    package('puppybot-esp32-flexscript.zip',
            {name: firmware / name for name in ('puppybot.bin', 'puppybot.elf', 'puppybot.map', 'puppybot.json')},
            'Classic ESP32 Flexscript serial firmware. Flash puppybot.bin at 0x1000.\n'
            'Back up the existing flash first. See src/firmware/README.md for wiring and enable/stop semantics.\n'
            'UART0: 115200 baud; STServo UART2: GPIO17 TX / GPIO16 RX, 1 Mbaud.\n'
            'This image does not provide Wi-Fi, WebSocket, BLE or Android wireless control.\n')
    files = {name: build / name for name in ('puppybot-runtime', 'puppybot', 'puppybot-simulator')}
    files['puppybot.json'] = ROOT / 'puppybot.json'
    package('puppybot-runtime-flexscript.zip', files,
            'Linux x86-64 native Flexscript runtime, CLI and lightweight serial simulator.\n'
            'Run ./puppybot-runtime from this directory; it defaults to a fake servo bus.\n'
            'Dashboard: http://127.0.0.1:8081/. Configuration: puppybot.json.\n'
            'See src/README.md for physical serial control and explicit output enable.\n')


if __name__ == '__main__':
    main()

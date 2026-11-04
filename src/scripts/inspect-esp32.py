#!/usr/bin/env python3
"""Independently verify ELF load bounds, ROM checksums and cached flash mapping."""
import hashlib
import json
from pathlib import Path
import struct
import sys


def inspect(elf_path, image_path):
    elf = Path(elf_path).read_bytes()
    image = Path(image_path).read_bytes()
    assert elf[:7] == b'\x7fELF\x01\x01\x01' and struct.unpack_from('<H', elf, 18)[0] == 94
    phoff = struct.unpack_from('<I', elf, 28)[0]
    phsize, phnum = struct.unpack_from('<HH', elf, 42)
    segments = []
    for index in range(phnum):
        kind, offset, address, _, size, memory, _, _ = struct.unpack_from('<8I', elf, phoff + index*phsize)
        if kind != 1 or not memory:
            continue
        assert size <= memory and offset+size <= len(elf)
        assert any(start <= address and address+memory <= end for start, end in
                   ((0x40080000, 0x400a0000), (0x3ffb0000, 0x3ffb8000),
                    (0x400d0000, 0x40300000), (0x3f400000, 0x3f700000)))
        segments.append((address, elf[offset:offset+size], memory))
    entry = struct.unpack_from('<I', elf, 24)[0]
    assert 0x40080000 <= entry < 0x400a0000
    assert image[0] == 0xe9 and image[1] == 2 and image[2] == 2
    assert struct.unpack_from('<H', image, 12)[0] == 0 and image[23] == 1
    assert struct.unpack_from('<I', image, 4)[0] == entry
    position, checksum = 24, 0xef
    for _ in range(image[1]):
        address, size = struct.unpack_from('<II', image, position)
        position += 8
        payload = image[position:position+size]
        assert len(payload) == size
        assert any(a == address and data == payload for a, data, _ in segments)
        for byte in payload:
            checksum ^= byte
        position += size
    check_at = position | 15
    assert not any(image[position:check_at]) and image[check_at] == checksum
    assert image[check_at+1:check_at+33] == hashlib.sha256(image[:check_at+1]).digest()
    irom = next(data for address, data, _ in segments if address == 0x400d0000)
    assert image[0x30000-0x1000:0x30000-0x1000+len(irom)] == irom
    assert len(image)+0x1000 <= 0x400000
    sections = struct.unpack_from('<I', elf, 32)[0]
    shsize, shnum = struct.unpack_from('<HH', elf, 46)
    for index in range(shnum):
        section = sections + index*shsize
        if struct.unpack_from('<I', elf, section+4)[0] == 2:
            offset, size = struct.unpack_from('<II', elf, section+16)
            for symbol in range(offset+16, offset+size, 16):
                assert struct.unpack_from('<H', elf, symbol+14)[0] != 0, 'unresolved ELF symbol'
    report = dict(chip='esp32', flashOffset='0x1000', entry=hex(entry), imageBytes=len(image),
                  sha256=hashlib.sha256(image).hexdigest(),
                  segments=[dict(address=hex(address), bytes=len(data), memoryBytes=memory) for address, data, memory in segments])
    Path(image_path).with_suffix('.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    print(json.dumps(inspect(*sys.argv[1:]), indent=2))

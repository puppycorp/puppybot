#!/usr/bin/env python3
"""Check the bounded native JSON parser against Python's independent parser."""
from pathlib import Path
import random
import struct
import subprocess
import sys

# This filename must not shadow the Python standard library json module.
BASE = Path(__file__).resolve().parent
sys.path = [p for p in sys.path if Path(p or '.').resolve() != BASE]
import json

ROOT = BASE.parents[1]


def main():
    rng = random.Random(51234)
    samples = [None, True, False, 0, -1, 2**63-1, 2**63, 2**64-1, 0.1, -0.0,
               '', 'hi\x00\n"\\🦊ä', {'arm': [{'angle': 90.0}], 'serial': 'PB-DEV-0001'}]
    def value(depth=0):
        pool = samples[:12]
        if depth < 4:
            pool += [[value(depth+1) for _ in range(rng.randrange(5))],
                     {f'key{i}': value(depth+1) for i in range(rng.randrange(5))}]
        return rng.choice(pool)
    for _ in range(200):
        samples.append(value())
    data = [json.dumps(x, ensure_ascii=bool(i % 2)).encode() for i, x in enumerate(samples)]
    data += [b'{"x":1,"x":2}', b'1e-999', b'{"x":-0}', b' "\\ud83e\\udd8a" ']
    bad = [b'', b'01', b'+1', b'[1,]', b'{"x":1,}', b'{"x" 1}', b'[true false]', b'null x',
           b'1e999', b'"\\ud800"', b'"\\udc00"', b'"\\ud800\\u0020"', b'"\xff"', b'"\xc0\x80"',
           b'"\xed\xa0\x80"', b'"\xf4\x90\x80\x80"', b'"\n"', b'"\\x20"', b'"\\u123"', b'"unterminated',
           b'['*34 + b'0' + b']'*34]
    records = data + bad
    payload = b''.join(struct.pack('<Q', len(s)) + s for s in records)
    result = subprocess.run([str(ROOT/'build/flex/json-probe')], input=payload, capture_output=True, check=True, timeout=30)
    at = 0
    for i, source in enumerate(records):
        valid, size = struct.unpack_from('<QQ', result.stdout, at); at += 16
        actual = result.stdout[at:at+size]; at += size
        if i >= len(data):
            assert not valid, source
        else:
            assert valid, source
            assert json.loads(actual) == json.loads(source), (source, actual)
    assert at == len(result.stdout)
    print(f'Host JSON: {len(data)} Unicode/numeric round trips and {len(bad)} malformed rejections passed')


if __name__ == '__main__':
    main()

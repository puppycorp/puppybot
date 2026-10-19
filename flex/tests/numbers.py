#!/usr/bin/env python3
"""Independent IEEE and decimal boundary checks for host JSON numbers."""
from pathlib import Path
import math
import random
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def bits(value):
    return struct.unpack('<Q', struct.pack('<d', value))[0]


def main():
    rng = random.Random(812735)
    values = [0.0, -0.0, 1.0, -1.0, math.pi, 2**-1074, 2**-1022, 1.7976931348623157e308,
              0.1, 1e-6, 1e-7, 1e16, 1e17, 3538.0, -7.15244988058]
    for _ in range(2000):
        raw = rng.getrandbits(64)
        if raw & 0x7ff0000000000000 != 0x7ff0000000000000:
            values.append(struct.unpack('<d', struct.pack('<Q', raw))[0])
    decimals = [repr(x) for x in values]
    decimals += ['0e99999', '-0.0e-99999', '1e-9999', '1e309', '1.7976931348623158e308',
                 '1.7976931348623159e308', '2.4703282292062327e-324', '2.4703282292062328e-324',
                 '9007199254740993', '18446744073709551615', '0.0000000000000000000000000000000000001']
    for _ in range(1000):
        digits = ''.join(str(rng.randrange(10)) for _ in range(rng.randrange(1, 100)))
        if digits[0] == '0':
            digits = '1' + digits[1:]
        decimals.append(('-' if rng.randrange(2) else '') + digits + 'e' + str(rng.randrange(-400, 350)))
    bad = ['', '+1', '01', '.5', '1.', '1e', '--1', 'nan', 'Infinity', '1 2', '1e+']
    payload = b''.join(struct.pack('<QQ', 0, len(s)) + s.encode() for s in decimals + bad)
    payload += b''.join(struct.pack('<QQ', 1, bits(x)) for x in values)
    result = subprocess.run([str(ROOT/'build/flex/numbers-probe')], input=payload, capture_output=True, check=True, timeout=30)
    at = 0
    for text in decimals + bad:
        error, actual = struct.unpack_from('<QQ', result.stdout, at); at += 16
        try:
            number = float(text)
            valid = text not in bad and math.isfinite(number)
        except ValueError:
            valid = False
        if bool(error) == valid or (valid and actual != bits(number)):
            raise AssertionError((text, error, hex(actual), hex(bits(number)) if valid else 'invalid'))
    for number in values:
        size, = struct.unpack_from('<Q', result.stdout, at); at += 8
        text = result.stdout[at:at+size].decode(); at += size
        if bits(float(text)) != bits(number):
            raise AssertionError(('format round trip', number, text))
    assert at == len(result.stdout)
    print(f'Host numbers: {len(decimals)+len(bad)} exact parses and {len(values)} IEEE round trips passed')


if __name__ == '__main__':
    main()

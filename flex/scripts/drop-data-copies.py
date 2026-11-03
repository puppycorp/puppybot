# Delete dataset copies in model folders (data.bin beside receipt.json) when a dataset (data.bin beside report.json,
# no receipt) with the receipt's dataSHA256 and the same size still exists and cmp finds the two identical.
# Usage: dropcopies.py ROOT SKIP_REGEX; prints one line per copy and a total.
import json, os, re, subprocess, sys
root, skip = sys.argv[1], re.compile(sys.argv[2])
sources, copies = {}, []
for d, dirs, files in os.walk(root):
    if 'data.bin' not in files:
        continue
    path = os.path.join(d, 'data.bin')
    try:
        if 'receipt.json' in files:
            copies.append((path, json.load(open(os.path.join(d, 'receipt.json'))).get('dataSHA256')))
        elif 'report.json' in files:
            h = json.load(open(os.path.join(d, 'report.json'))).get('dataSHA256')
            if h:
                sources.setdefault(h, []).append(path)
    except (OSError, ValueError):
        pass
freed = kept = 0
for path, h in sorted(copies):
    if skip.search(path):
        print('skip (excluded)', path); kept += 1; continue
    size = os.path.getsize(path)
    match = next((s for s in sources.get(h, []) if os.path.getsize(s) == size), None) if h else None
    if match is None:
        print('keep (no matching dataset)', path); kept += 1; continue
    if subprocess.run(['cmp', '-s', path, match]).returncode != 0:
        print('keep (differs from', match + ')', path); kept += 1; continue
    os.remove(path); freed += size
    print('deleted', path, '=', match, flush=True)
print(f'deleted {freed / 1e9:.0f} GB of copies; kept {kept}')

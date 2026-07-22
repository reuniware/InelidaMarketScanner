#!/usr/bin/env python3
import os

SIG = 'Reuniware Systems'
missing = []
signed = []

for root, dirs, files in os.walk('.'):
    if 'ebooks' in root or '.git' in root or '__pycache__' in root:
        continue
    for f in files:
        if f.endswith('.md'):
            fpath = os.path.join(root, f)
            with open(fpath, 'r', encoding='utf-8', errors='replace') as fh:
                c = fh.read()
            short = fpath.replace('\\', '/').replace('./', '')
            if SIG in c:
                signed.append(short)
            elif 'Reuniware' in c:
                print(f'OLD: {short}')
                missing.append(short)
            else:
                print(f'MISSING: {short}')
                missing.append(short)

print()
print(f'Signed: {len(signed)}')
print(f'Missing/Old: {len(missing)}')
for m in missing:
    print(f'  -> {m}')

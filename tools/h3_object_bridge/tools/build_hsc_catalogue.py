"""Build facts-only offline signatures from a pinned c20 checkout (GPL-3.0).

Usage: python tools/build_hsc_catalogue.py C:/references/c20
Descriptions and implementation code are not copied. The runtime never fetches
network content. Optional user catalogues use this same versioned JSON contract.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

repo = Path(sys.argv[1]).resolve()
revision = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
result = {'format': 'foundry.hsc-signatures', 'version': 1, 'evidence': {
    'repository': 'https://github.com/Sigmmma/c20', 'revision': revision,
    'h3_url': 'https://c20.reclaimers.net/h3/engine/scripting/',
    'reach_url': 'https://c20.reclaimers.net/hr/engine/scripting/',
    'license': 'GPL-3.0', 'basis': 'Engine hs_doc signature snapshots, not runtime tests', 'files': []}}
for game, key in [('h3', 'h3'), ('hr', 'reach')]:
    path = f'src/data/hs_docs/{game}/hs_doc.txt'
    data = subprocess.check_output(['git', '-C', str(repo), 'show', f'{revision}:{path}'])
    result['evidence']['files'].append({'path': path, 'sha256': hashlib.sha256(data).hexdigest()})
    profile = {'functions': {}, 'globals': {}}
    global_section = False
    for line in data.decode('utf-8-sig').splitlines():
        if 'GLOBALS' in line and line.startswith(';'):
            global_section = True
        match = re.fullmatch(r'\(<([^>]+)>\s+(\S+?)(?:\s+(.*))?\)', line.strip())
        if not match:
            continue
        returns, name, args = match.groups()
        if global_section:
            profile['globals'][name] = returns
            continue
        args = args or ''
        types = re.findall(r'<([^>]+)>', args)
        required = re.findall(r'<([^>]+)>', args.split('[', 1)[0])
        variadic = any('(s)' in t or '...' in t for t in types) or '...' in args
        signature = {'result': returns, 'args': types, 'raw': line.strip(),
                     'min_args': len(required), 'max_args': None if variadic else len(types)}
        # At least one expression for documented variadic begin/and/arithmetic.
        if signature not in profile['functions'].setdefault(name, []):
            profile['functions'][name].append(signature)
    result[key] = profile
    print(game, len(profile['functions']), 'functions,', len(profile['globals']), 'globals')
out = Path(__file__).resolve().parents[1] / 'data/hsc_signatures.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(result, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')

"""Verify the extension version, source files, and bundled Windows helpers."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tomllib
from zipfile import ZipFile

path = Path(sys.argv[1])
root = Path(__file__).resolve().parents[1]
addon = root / 'blender/addons/io_scene_foundry'
version = tomllib.loads((addon / 'blender_manifest.toml').read_text())['version']
commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
files = ['__init__.py', 'h3_import/animations.py', 'h3_import/animation_builder.py',
         'h3_import/animation_append.py', 'h3_import/animation_ops.py']
helpers = ['h3-object-bridge', 'h3-shader-bridge', 'h3-animation-bridge']
result = {'version': version, 'source_commit': commit, 'archive': path.name,
          'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'helpers': {}, 'source_files': {}}
with ZipFile(path) as z:
    assert z.testzip() is None, 'Archive integrity failure'
    assert tomllib.loads(z.read('blender_manifest.toml').decode())['version'] == version
    assert not any(Path(n).suffix.lower() in ('.ttf', '.otf', '.woff', '.woff2') for n in z.namelist()), 'Font file in package'
    for name in helpers:
        data = z.read(f'h3_import/bin/{name}.exe')
        assert data[:2] == b'MZ', name
        offset = struct.unpack_from('<I', data, 0x3c)[0]
        assert data[offset:offset+4] == b'PE\0\0', name
        assert struct.unpack_from('<H', data, offset+4)[0] == 0x8664, name
        result['helpers'][name] = {'machine': 'AMD64', 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    for name in files:
        data = z.read(name)
        assert data == (addon / name).read_bytes(), name
        result['source_files'][name] = hashlib.sha256(data).hexdigest()
    result['zip_integrity'] = 'passed'
    result['font_files'] = 0
output = path.with_suffix('.verification.json')
output.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))

"""Check the release archive against its checkout before publishing the feed."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tomllib
from zipfile import ZipFile

root = Path(__file__).resolve().parents[1]
addon = root / 'blender/addons/io_scene_foundry'
archive = Path(sys.argv[1])
sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, cwd=root).strip()
version = tomllib.loads((addon / 'blender_manifest.toml').read_text())['version']
with ZipFile(archive) as package:
    assert package.testzip() is None
    assert len(package.namelist()) == len(set(package.namelist()))
    assert not any(Path(n).suffix.lower() in {'.ttf', '.otf', '.woff', '.woff2'} for n in package.namelist())
    assert tomllib.loads(package.read('blender_manifest.toml').decode())['version'] == version
    for path in addon.rglob('*.py'):
        name = path.relative_to(addon).as_posix()
        if '__pycache__' in path.parts:
            continue
        assert package.read(name) == path.read_bytes(), name
    for name in ('h3-object-bridge', 'h3-shader-bridge'):
        data = package.read(f'h3_import/bin/{name}.exe')
        assert data[:2] == b'MZ'
        offset = struct.unpack_from('<I', data, 0x3c)[0]
        assert data[offset:offset + 4] == b'PE\0\0'
        assert struct.unpack_from('<H', data, offset + 4)[0] == 0x8664
result = {'version': version, 'source_sha': sha}
(archive.parent / 'build.json').write_text(json.dumps(result, indent=2))
print('RELEASE_VERIFIED', json.dumps({**result, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}))

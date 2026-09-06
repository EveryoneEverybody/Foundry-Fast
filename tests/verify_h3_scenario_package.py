"""Check scenario prototype sources and all four bundled Windows helpers."""
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
path = Path(sys.argv[1])
version = tomllib.loads((addon / 'blender_manifest.toml').read_text())['version']
assert version == '1.9.42'
result = {'version': version, 'source_commit': subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
          'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'source_files': {}, 'helpers': {}}
with ZipFile(path) as archive:
    assert archive.testzip() is None
    assert not any(Path(n).suffix.lower() in ('.ttf','.otf','.woff','.woff2') for n in archive.namelist())
    assert tomllib.loads(archive.read('blender_manifest.toml').decode())['version'] == version
    files = list((addon / 'h3_import').rglob('*.py')) + [addon / '__init__.py', addon / 'blender_manifest.toml']
    for file in files:
        name = file.relative_to(addon).as_posix()
        data = archive.read(name)
        assert data == file.read_bytes(), name
        result['source_files'][name] = hashlib.sha256(data).hexdigest()
    for name in ('h3-object-bridge','h3-shader-bridge','h3-animation-bridge','h3-scenario-inspect'):
        data = archive.read(f'h3_import/bin/{name}.exe')
        assert data[:2] == b'MZ'
        offset = struct.unpack_from('<I',data,0x3c)[0]
        assert data[offset:offset+4] == b'PE\0\0'
        assert struct.unpack_from('<H',data,offset+4)[0] == 0x8664
        result['helpers'][name] = {'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'machine':'AMD64'}
result['zip_integrity'] = 'passed'
path.with_suffix('.verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))

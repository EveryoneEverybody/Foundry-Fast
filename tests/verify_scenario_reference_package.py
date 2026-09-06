"""Verify scenario additions alongside the existing H3 package checks."""
import hashlib
import json
from pathlib import Path
import runpy
import sys
from zipfile import ZipFile

folder = Path(__file__).resolve().parent
runpy.run_path(str(folder / 'verify_h3_animation_package.py'), run_name='__main__')
path = Path(sys.argv[1])
report_path = path.with_suffix('.verification.json')
report = json.loads(report_path.read_text())
addon = folder.parent / 'blender/addons/io_scene_foundry'
with ZipFile(path) as archive:
    for name in (
        'scenario_reference.py',
        'scenario_static_direct.py',
        'scenario_reference_direct_patch.py',
        'perf_bitmap_cache.py',
    ):
        data = archive.read(name)
        assert data == (addon / name).read_bytes(), name
        report['source_files'][name] = hashlib.sha256(data).hexdigest()
report_path.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))

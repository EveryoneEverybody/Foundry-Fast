"""Check worker sources alongside all scenario and H3 package requirements."""
import hashlib
import json
from pathlib import Path
import runpy
import sys
from zipfile import ZipFile

folder = Path(__file__).resolve().parent
runpy.run_path(str(folder / 'verify_scenario_reference_package.py'), run_name='__main__')
path = Path(sys.argv[1])
report_path = path.with_suffix('.verification.json')
report = json.loads(report_path.read_text())
addon = folder.parent / 'blender/addons/io_scene_foundry'
files = ['parallel_bitmaps.py', 'managed_blam/bitmap.py']
files.extend(str(p.relative_to(addon)).replace('\\', '/') for p in (addon / 'bitmap_workers').glob('*.py'))
with ZipFile(path) as archive:
    assert len(archive.namelist()) == len(set(archive.namelist())), 'Duplicate ZIP entries'
    for name in files:
        data = archive.read(name)
        assert data == (addon / name).read_bytes(), name
        compile(data, name, 'exec')
        report['source_files'][name] = hashlib.sha256(data).hexdigest()
report['bitmap_worker_source_files'] = sorted(files)
report_path.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))

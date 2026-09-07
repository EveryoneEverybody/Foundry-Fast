"""Package a verified extension with the one-command Windows compiler runner."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tomllib
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parents[1]
extension = Path(sys.argv[1]).resolve(strict=True)
with ZipFile(extension) as source:
    version = tomllib.loads(source.read('blender_manifest.toml').decode())['version']
    name = f'Foundry-H3-proof-box-{version}-windows'
    output = extension.parent/(name+'.zip')
    hashes = {}
    with ZipFile(output,'w',ZIP_DEFLATED) as target:
        for member in source.infolist():
            if member.is_dir():continue
            content = source.read(member)
            path = 'io_scene_foundry/'+member.filename
            target.writestr(path,content)
            hashes[path] = hashlib.sha256(content).hexdigest()
        for path,local in [('Run-ProofBox.ps1',root/'tools/Run-ProofBox.ps1'),
                           ('README.md',root/'docs/h3-proof-box.md')]:
            content = local.read_bytes()
            target.writestr(path,content)
            hashes[path] = hashlib.sha256(content).hexdigest()
        target.writestr('build.json',json.dumps(dict(format='foundry.h3-proof-box-package',version=version,
            source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
            extension_sha256=hashlib.sha256(extension.read_bytes()).hexdigest(),files=hashes),indent=2))
with ZipFile(output) as target:
    assert target.testzip() is None
    for path,sha in hashes.items():assert hashlib.sha256(target.read(path)).hexdigest()==sha,path
output.with_suffix('.sha256').write_text(hashlib.sha256(output.read_bytes()).hexdigest()+'  '+output.name+'\n')
print(output)

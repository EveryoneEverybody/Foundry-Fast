"""Decode supported object families into shared, hash-pinned source records."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment import object_ir
from port_environment.model import stable_hash
from port_environment.paths import digest,relative,atomic_json


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def decode(args):
    inventory=read(args.inventory); root=Path(args.tags_root).resolve(strict=True)
    output=Path(args.output).resolve(); helpers=Path(args.helpers).resolve(strict=True)
    if output.is_relative_to(root):raise ValueError('Output must be outside source tags')
    output.mkdir(parents=True,exist_ok=True)
    selected={'scenery','crates','machines','controls'}
    cache=output/'metadata';cache.mkdir(exist_ok=True)
    results=[]
    def metadata(source):
        tag=(root/relative(source)).resolve(strict=True)
        if not tag.is_relative_to(root):raise ValueError('Dependency escapes source root')
        path=cache/(stable_hash(source)[:24]+'.json')
        if not path.exists():
            with path.with_suffix('.log').open('xb') as stream:
                result=subprocess.run([str(helpers/'h3-tag-authoring.exe'),str(root),str(tag),str(path)],
                    stdout=stream,stderr=subprocess.STDOUT)
            if result.returncode:raise RuntimeError('Source metadata failed: '+source+'; '+str(path.with_suffix('.log')))
        data=read(path)
        if data['source_tag']!=source or data['source_sha256']!=digest(tag):
            raise ValueError('Source metadata cache differs from current tag: '+source)
        return data
    for source,identity in sorted(inventory['object_dependencies'].items()):
        if not any(u['family'] in selected for u in identity['source_palette_uses']):continue
        name=Path(source).stem+'_'+stable_hash(source)[:12]; directory=output/name
        receipt=directory/'decode-report.json'
        if receipt.exists():
            previous=read(receipt)
            if all((Path(p).is_file() and digest(p)==h) for p,h in previous.get('source_hashes',{}).items()):
                results.append(previous);print('Reused '+source,flush=True);continue
            raise ValueError('Object source changed since receipt: '+source)
        directory.mkdir(exist_ok=True); begin=time.monotonic()
        row=dict(source_tag=source,source_group=identity['source_group'],directory=str(directory),
                 native_status='NOT_GENERATED',runtime_status='NOT_TESTED')
        hashes={}
        try:
            obj=metadata(source);hashes[str(root/source)]=obj['source_sha256']
            model_path=object_ir.dependency(obj,'model'); model=metadata(model_path) if model_path else None
            if model:hashes[str(root/model_path)]=model['source_sha256']
            # Source metadata survives even when render/collision decoding fails.
            row['object_ir']=object_ir.describe(identity,obj,model)
            geometry_dir=directory/'geometry';geometry_dir.mkdir(exist_ok=True)
            asset=geometry_dir/'asset.h3asset.json'
            command=[str(helpers/'h3-object-bridge.exe'),'--tags-root',str(root),'--input',str(root/source),
                     '--output',str(geometry_dir),'--collision','--physics']
            with (directory/'geometry.log').open('xb') as stream:
                status=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT).returncode
            row['geometry_command']=command;row['geometry_exit_code']=status
            if status:raise RuntimeError('Shared object geometry decoder failed; see '+str(directory/'geometry.log'))
            geometry=read(asset)
            physics_path=geometry.get('dependencies',{}).get('physics_model')
            physics=metadata(physics_path) if physics_path else None
            for dep in geometry.get('dependencies',{}).values():hashes[str(root/dep)]=digest(root/dep)
            row['object_ir']=object_ir.describe(identity,obj,model,geometry,physics)
            row.update(status='SOURCE_DECODED',asset=str(asset),asset_sha256=digest(asset))
            if row['object_ir'].get('animation_graph'):
                graph=metadata(row['object_ir']['animation_graph'])
                row['animation_metadata']=graph
                hashes[str(root/graph['source_tag'])]=graph['source_sha256']
        except (ValueError,OSError,RuntimeError) as exc:
            row.update(status='DEFERRED',reason=str(exc),classification='BLOCKING_UNKNOWN')
        row.update(source_hashes=hashes,seconds=time.monotonic()-begin)
        atomic_json(receipt,row);results.append(row)
        atomic_json(output/'object-decode-inventory.json',dict(format='foundry.h3-object-decode-inventory',version=1,
            source_scenario=inventory['source_scenario'],objects=results,complete=False))
        print(row['status']+' '+source,flush=True)
    atomic_json(output/'object-decode-inventory.json',dict(format='foundry.h3-object-decode-inventory',version=1,
        source_scenario=inventory['source_scenario'],objects=results,complete=True))
    print(json.dumps(dict(objects=len(results),decoded=sum(r['status']=='SOURCE_DECODED' for r in results),
                         deferred=sum(r['status']=='DEFERRED' for r in results))),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('inventory','tags-root','output','helpers'):p.add_argument('--'+name,required=True)
    decode(p.parse_args())


if __name__=='__main__':main()

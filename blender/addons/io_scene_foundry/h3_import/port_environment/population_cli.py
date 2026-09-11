"""Guarded runner for the explicit existing-scenario population mode."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

from .model import stable_hash
from .paths import OutputPaths, atomic_json, build_lock, digest
from .native_placements import SUPPORTED


def run(args, plan):
    if not args.integrate_inventory or not args.population_root_receipts:
        raise ValueError('Population requires source inventory and per-root native receipts')
    if args.limit or args.retry_source or args.reuse_compiled_from:
        raise ValueError('Population cannot run as a limited/retry object build')
    paths = OutputPaths(args.h3_root,args.reach_root,plan['target']['namespace'],allow_nested=True)
    directory = Path(args.work_dir).resolve()
    if directory.is_relative_to(paths.reach) or directory.is_relative_to(paths.h3):
        raise ValueError('Population evidence must be outside the tag kits')
    key = paths.fingerprint()+'-'+stable_hash(paths.namespace)[:16]
    with build_lock(Path(tempfile.gettempdir())/'foundry_h3_port_locks'/key):
        output = directory/'population-build'/'runs'/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
        output.mkdir(parents=True)
        scenario = paths.owned_tag(paths.scenario+'.scenario')
        before_sha = digest(scenario)
        shutil.copyfile(scenario,output/'scenario.before.scenario')
        protected = {str(paths.reach/p):h for p,h in paths.snapshot().items()}
        receipts = json.loads(Path(args.population_root_receipts).read_text())
        receipt_files={p for receipt in receipts.values() for p in receipt['output_files']}
        protected.update({p:digest(p) for p in receipt_files if p not in protected})
        if args.population_protected_manifest:
            rows = json.loads(Path(args.population_protected_manifest).read_text(encoding='utf-8-sig'))
            for row in rows:
                actual = digest(row['path'])
                if Path(row['path']).resolve()!=scenario.resolve() and actual != row['sha256']:
                    raise ValueError('Protected baseline has drifted: '+row['path'])
                protected[row['path']] = actual
        atomic_json(output/'protected-before.json',protected)
        before_xml = output/'before.xml'
        with (output/'tool-before.log').open('wb') as log:
            result = subprocess.run([str(paths.reach/'tool.exe'),'export-tag-to-xml',str(scenario),str(before_xml)],
                                    cwd=paths.reach,stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:
            raise ValueError('Native baseline XML export failed')
        inputs = [args.plan,args.integrate_inventory,args.population_root_receipts,str(before_xml)]
        if args.population_provenance:
            inputs.append(args.population_provenance)
        config = dict(plan=str(Path(args.plan).resolve()),inventory=str(Path(args.integrate_inventory).resolve()),
            root_receipts=str(Path(args.population_root_receipts).resolve()),
            provenance=str(Path(args.population_provenance).resolve()) if args.population_provenance else None,
            inputs={str(Path(p).resolve()):digest(p) for p in inputs},before_xml=str(before_xml),
            scenario_before_sha256=before_sha,run_directory=str(output),h3_root=str(paths.h3),reach_root=str(paths.reach),
            families=args.population_family or list(SUPPORTED),dry_run=args.population_dry_run)
        atomic_json(output/'config.json',config)
        command = [str(Path(args.blender).resolve(strict=True)),'--background','--factory-startup','--python-exit-code','1',
                   '--python',str(Path(__file__).with_name('population_worker.py')),'--',str(output/'config.json')]
        with (output/'blender-reach-worker.log').open('wb') as log:
            process = subprocess.run(command,cwd=paths.reach,stdout=log,stderr=subprocess.STDOUT)
        after = {p:digest(p) if Path(p).is_file() else None for p in protected}
        unexpected = [p for p in protected if Path(p).resolve()!=scenario.resolve() and protected[p]!=after[p]]
        atomic_json(output/'protected-after.json',dict(files=after,unexpected_changes=unexpected))
        result_path = output/'population-result.json'
        result = json.loads(result_path.read_text()) if result_path.is_file() else {'status':'WORKER_FAILED'}
        result.update(command=command,run_directory=str(output),exit_code=process.returncode,
                      protected_files_unchanged=not unexpected)
        if process.returncode or unexpected:
            result['status']='FAILED'
        atomic_json(result_path,result)
        atomic_json(directory/'population-build'/'latest.json',dict(run_directory=str(output),status=result['status']))
        print(json.dumps(dict(status=result['status'],run_directory=str(output),
                              semantic_mutations=result.get('semantic_mutations')),indent=2),flush=True)
        return 0 if result['status'] in {'DRY_RUN','NATIVE_AUTHORED_READBACK_VERIFIED'} else 1

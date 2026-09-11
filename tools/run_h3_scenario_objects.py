"""Compile source-backed non-unit objects under the environment ownership lock."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment.paths import OutputPaths,Ownership,atomic_json,build_lock,digest
from port_environment.model import stable_hash
from port_environment.snapshot import verify_files
from port_environment.object_receipts import verify_reuse


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('plan','h3-root','reach-root','blender','work-dir','device-animations'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--limit',type=int)
    parser.add_argument('--integrate-inventory')
    parser.add_argument('--compiled-report')
    parser.add_argument('--defer-zone-switches',action='store_true',help='Keep source switches in IR when the native kit cannot persist the table; retain static volumes')
    parser.add_argument('--reuse-compiled-from',help='Completed same-plan receipt whose entire output snapshot still matches')
    parser.add_argument('--retry-source',action='append',help='Retry only these source identities; retain every other prior result')
    parser.add_argument('--populate-existing',action='store_true',help='Reconcile selected object families without replacing other scenario tables')
    parser.add_argument('--population-root-receipts')
    parser.add_argument('--population-provenance')
    parser.add_argument('--population-protected-manifest')
    parser.add_argument('--population-family',action='append',choices=('scenery','crates','machines','controls'))
    parser.add_argument('--population-dry-run',action='store_true')
    args=parser.parse_args()
    plan=json.loads(Path(args.plan).read_text())
    if stable_hash({k:v for k,v in plan.items() if k!='plan_sha256'})!=plan['plan_sha256']:
        raise ValueError('Object plan integrity differs')
    print('Verifying source integrity',flush=True)
    verify_files(plan['source_files'])
    if args.populate_existing:
        from port_environment.population_cli import run
        return run(args,plan)
    paths=OutputPaths(args.h3_root,args.reach_root,plan['target']['namespace'],allow_nested=True)
    owner=Ownership(paths,args.work_dir)
    key=paths.fingerprint()+'-'+stable_hash(paths.namespace)[:16]
    with build_lock(Path(tempfile.gettempdir())/'foundry_h3_port_locks'/key):
        print('Verifying current generated output ownership',flush=True)
        before=owner.preflight()
        reuse=None
        if args.retry_source and not args.reuse_compiled_from:raise ValueError('Selected retry requires a prior receipt')
        if args.reuse_compiled_from:
            if args.limit or args.integrate_inventory:raise ValueError('Receipt retries cannot be combined with limits or placement integration')
            reuse=json.loads(Path(args.reuse_compiled_from).read_text())
            verified_outputs=verify_reuse(reuse,plan,before,args.retry_source)
        build_id=time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
        directory=owner.directory/('placement-build' if args.integrate_inventory else 'object-build');run=directory/'runs'/build_id
        run.mkdir(parents=True)
        report=dict(status='BUILDING',plan_sha256=plan['plan_sha256'],run_directory=str(run),
            source_validation_basis=dict(verified_files=plan['source_files']),runtime_status='NOT_TESTED')
        config=dict(plan=str(Path(args.plan).resolve()),h3_root=str(paths.h3),reach_root=str(paths.reach),
            run_directory=str(run),report_directory=str(directory),device_animations=str(Path(args.device_animations).resolve()),
            snapshot_input=report['source_validation_basis'],limit=args.limit)
        if reuse:
            config.update(reuse_compiled_from=str(Path(args.reuse_compiled_from).resolve()),
                reuse_receipt_sha256=digest(args.reuse_compiled_from),reuse_verified_output_files=verified_outputs,retry_sources=args.retry_source)
        if args.integrate_inventory:
            if not args.compiled_report:raise ValueError('Integration requires a completed native object receipt')
            config.update(inventory=str(Path(args.integrate_inventory).resolve()),compiled_report=str(Path(args.compiled_report).resolve()),defer_zone_switches=args.defer_zone_switches)
        atomic_json(run/'config.json',config)
        script='placement_worker.py' if args.integrate_inventory else 'object_worker.py'
        report['command']=[str(Path(args.blender).resolve(strict=True)),'--background','--factory-startup',
            '--python-exit-code','1','--python',str(Path(__file__).resolve().parents[1]/
                'blender/addons/io_scene_foundry/h3_import/port_environment'/script),'--',str(run/'config.json')]
        owner.save('BUILDING',before,build_id)
        print('Object build: '+str(run),flush=True)
        try:
            with (run/'blender-reach-worker.log').open('xb') as log:
                result=subprocess.run(report['command'],cwd=paths.reach,stdout=log,stderr=subprocess.STDOUT)
            report['exit_code']=result.returncode
            worker=run/'worker-report.json'
            report['worker']=json.loads(worker.read_text()) if worker.is_file() else {}
            report['status']='COMPLETE' if result.returncode==0 else 'FAILED'
        except Exception as exc:
            report.update(status='FAILED',failure=str(exc))
            raise
        finally:
            print('Worker finished; hashing completed output snapshot',flush=True)
            after=paths.snapshot()
            owner.save(report['status'],after,build_id)
            report['generated_files']=[dict(path=p,sha256=h) for p,h in after.items()]
            atomic_json(run/(paths.asset+'_build_report.json'),report)
            atomic_json(directory/(paths.asset+'_build_report.json'),report)
        print(dict(status=report['status'],objects=len(report['worker'].get('objects',[]))),flush=True)
        return 0 if report['status']=='COMPLETE' else 1


if __name__=='__main__':sys.exit(main())

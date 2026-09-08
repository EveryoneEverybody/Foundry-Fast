"""Re-export an owned source-scene checkpoint with source-proven seam ownership."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import traceback
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment.paths import OutputPaths, Ownership, atomic_json, build_lock, digest
from port_environment.model import stable_hash
from port_environment.snapshot import verify_files
from port_environment.cli import Commands, expected_tags, cleanup_dependencies, finish_stage_timings, write_summary


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous-run',required=True)
    parser.add_argument('--blender',required=True)
    args=parser.parse_args()
    prior=Path(args.previous_run).resolve(strict=True)
    original=read(prior/'worker-config.json');plan=read(original['plan'])
    paths=OutputPaths(original['h3_root'],original['reach_root'],original['namespace'],allow_nested=True)
    owner=Ownership(paths,original['report_directory'])
    if prior.parent!=owner.directory/'runs':raise ValueError('Checkpoint must belong to this environment build')
    if plan['version']!=2 or plan.get('unsupported'):raise ValueError('Resume requires a resolved multi-BSP source plan')
    if stable_hash({k:v for k,v in plan.items() if k!='plan_sha256'})!=original['plan_sha256']:
        raise ValueError('Source plan changed')
    if not original.get('snapshot_input'):raise ValueError('Scene resume requires a sealed source snapshot')
    verify_files(original['snapshot_input']['verified_files'])
    previous=read(prior/(paths.asset+'_build_report.json'))
    old_worker=read(prior/'worker-report.json')
    checkpoint=paths.destination('data',paths.asset+'.blend')
    expected={r['path']:r['sha256'] for r in previous['generated_files']}
    identity=checkpoint.relative_to(paths.reach).as_posix()
    if not old_worker.get('construction_checkpoint') or expected.get(identity)!=digest(checkpoint):
        raise ValueError('Saved source scene must match the completed ownership snapshot')
    blender=Path(args.blender).resolve(strict=True)
    if str(blender) not in previous['build_tools_and_project']:raise ValueError('Use the original Blender executable')
    for path,sha in previous['build_tools_and_project'].items():
        if digest(path)!=sha:raise ValueError('Native tool/project changed: '+path)
    addon=Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry'
    key=paths.fingerprint()+'-'+stable_hash(paths.namespace)[:16]
    with build_lock(Path(tempfile.gettempdir())/'foundry_h3_port_locks'/key):
        before=owner.preflight()
        if before.get(identity)!=expected[identity]:raise ValueError('Checkpoint changed before lock')
        build_id=time.strftime('%Y%m%d-%H%M%S')+'-scene-'+uuid.uuid4().hex[:8]
        run=owner.directory/'runs'/build_id;run.mkdir()
        for name in ('environment.plan.json','source-semantic-resolution.json','source-dependencies.json',
                     'unsupported-semantics.json','accepted-snapshot-inputs.json'):
            if (prior/name).is_file():shutil.copyfile(prior/name,run/name)
        config=dict(original,plan=str(run/'environment.plan.json'),run_directory=str(run),
            validation_only=False,export_existing_scene=str(checkpoint),checkpoint_sha256=expected[identity],
            expected_outputs=before,previous_worker_report=str(prior/'worker-report.json'),
            previous_worker_sha256=digest(prior/'worker-report.json'))
        atomic_json(run/'worker-config.json',config)
        report=deepcopy(previous)
        report.update(build_id=build_id,run_directory=str(run),plan=config['plan'],status='BUILDING',
            engineering_success=False,tool_invocations=[],failures=[],lighting_status='NOT_RUN',
            scene_resumed_from=dict(run=str(prior),report_sha256=digest(prior/(paths.asset+'_build_report.json')),
                checkpoint_sha256=expected[identity],prior_status=previous['status']),
            compiler_source_hashes={p.relative_to(addon).as_posix():digest(p) for p in addon.rglob('*.py')})
        report.pop('failure',None);report.pop('first_authoritative_failure',None)
        commands=Commands(run,report);started=time.perf_counter()
        owner.save('BUILDING',before,build_id)
        print('Scene resume: '+str(run),flush=True)
        try:
            env=dict(os.environ,BLENDER_USER_CONFIG=str(run/'blender-config'),BLENDER_USER_SCRIPTS=str(run/'blender-scripts'))
            commands.run('blender-reach-worker',[blender,'--background','--factory-startup','--python-exit-code','1',
                '--python',addon/'h3_import/port_environment/worker.py','--',run/'worker-config.json'],addon,env)
            result=read(run/'worker-report.json')
            if result['status']!='COMPLETE':raise ValueError('Native scene export/validation did not complete')
            for tag in expected_tags(plan):
                if not paths.owned_tag(tag).is_file():raise ValueError('Expected native tag is absent: '+tag)
            report.update(status='GENERATED',engineering_success=True)
            (owner.directory/(paths.asset+'_init_snippet.txt')).write_text('game_start '+paths.scenario.replace('/','\\')+'\n',encoding='ascii')
        except Exception as exc:
            report.update(status='FAILED',failure=str(exc))
            report['failures'].append(dict(message=str(exc),traceback=traceback.format_exc()))
        finally:
            report['seconds']=time.perf_counter()-started
            if (run/'worker-report.json').is_file():
                report['worker']=read(run/'worker-report.json')
                report['tool_invocations'].extend(report['worker'].get('tool_invocations',[]))
                report['lighting_status']=report['worker'].get('lighting_status','NOT_RUN')
                if report['worker'].get('failure'):report['first_authoritative_failure']=report['worker']['failure']
            after=paths.snapshot()
            report['generated_files']=[dict(path=p,sha256=h,previous_sha256=before.get(p)) for p,h in sorted(after.items())]
            owner.save(report['status'],after,build_id)
            finish_stage_timings(report);cleanup_dependencies(run)
            write_summary(run,report);write_summary(owner.directory,report)
        print(report['status']+': '+str(run),flush=True)
        return 0 if report['status']=='GENERATED' else 1


if __name__=='__main__':sys.exit(main())

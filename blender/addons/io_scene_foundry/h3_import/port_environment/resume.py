"""Resume read-only validation of hash-identical, owned native output."""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import time
import traceback
import uuid

from .paths import OutputPaths, Ownership, atomic_json, build_lock, digest
from .model import stable_hash


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def require_outputs(actual, expected):
    if not expected or actual != expected:
        differences=sorted(k for k in set(actual)|set(expected) if actual.get(k)!=expected.get(k))
        raise ValueError('Native validation requires identical owned outputs: '+', '.join(differences[:5]))


def require_completed_authoring(worker):
    energy=worker.get('lighting_evidence',{}).get('vmf_energy_statistics',[])
    if (worker.get('stage')!='native tag validation' or
            not worker.get('lighting_status','').startswith('REACH_FAUX_') or
            worker.get('geometry_tool_errors')!=[] or
            worker.get('lighting_evidence',{}).get('errors')!=[] or
            not energy or not all(math.isfinite(float(x)) for x in energy) or not any(float(x)>0 for x in energy)):
        raise ValueError('Validation resume requires completed geometry and verified Faux')
    for row in worker.get('tool_invocations',[]):
        if row.get('exit_code')==0:
            continue
        command=row.get('command',[])
        if len(command)<2 or command[1]!='export-tag-to-xml':
            raise ValueError('Unsuccessful authoring operation prevents validation resume')


def xml_cache(prior, worker, paths, outputs):
    """Bind completed XML receipts to their original successful Tool commands."""
    commands={str(Path(row['command'][3]).resolve()):row['command'] for row in worker['tool_invocations']
              if row.get('exit_code')==0 and len(row.get('command',[]))==4
              and row['command'][1]=='export-tag-to-xml'}
    cache={}
    for row in worker.get('native_xml_validation',[]):
        xml=Path(row['path']).resolve(strict=True)
        if not xml.is_relative_to((prior/'native-tag-xml').resolve()):
            raise ValueError('Cached XML escapes the previous native validation directory')
        command=commands.get(str(xml))
        if not command or row['status']!='WELL_FORMED_STREAMED' or digest(xml)!=row['sha256']:
            raise ValueError('Native XML receipt lacks unchanged successful Tool evidence')
        source=Path(command[2]).resolve(strict=True)
        if not any(source.is_relative_to(base) for base in paths.tag_directories()):
            raise ValueError('Cached native XML belongs to another target')
        identity=source.relative_to(paths.reach).as_posix()
        if identity not in outputs or digest(source)!=outputs[identity]:
            raise ValueError('Native XML source no longer matches the owned output')
        cache[str(source)]=dict(row,source_sha256=outputs[identity])
    return cache


def validate_existing(args):
    from .cli import Commands, cleanup_dependencies, expected_tags, finish_stage_timings, write_summary
    if args.plan_only:
        raise ValueError('Validation resume and plan-only are different operations')
    prior=Path(args.validate_existing_run).resolve(strict=True)
    old_config=read(prior/'worker-config.json')
    paths=OutputPaths(args.h3_root,args.reach_root,args.namespace,allow_nested=True)
    ownership=Ownership(paths,args.work_dir)
    if (prior.parent!=ownership.directory/'runs' or
            Path(old_config['report_directory']).resolve()!=ownership.directory or
            Path(old_config['h3_root']).resolve()!=paths.h3 or
            Path(old_config['reach_root']).resolve()!=paths.reach or
            old_config['namespace']!=paths.namespace):
        raise ValueError('Validation resume must use the original target and report directory')
    old_report_path=prior/(paths.asset+'_build_report.json')
    if not old_report_path.is_file():
        old_report_path=prior/'proof_box_build_report.json'
    old_report=read(old_report_path)
    old_worker=read(prior/'worker-report.json')
    require_completed_authoring(old_worker)
    if (old_report['source_scenario']!=args.scenario.replace('\\','/') or
            old_report['source_zone_set']!=args.zone_set):
        raise ValueError('Validation resume cannot change source selection')
    plan=read(prior/'environment.plan.json')
    if stable_hash({k:v for k,v in plan.items() if k!='plan_sha256'})!=old_config['plan_sha256']:
        raise ValueError('Previous authoring plan changed')
    if plan.get('unsupported'):
        raise ValueError('Validation cannot bypass source contracts')
    addon=Path(__file__).resolve().parents[2]
    blender=Path(args.blender).resolve(strict=True)
    if str(blender) not in old_report['build_tools_and_project']:
        raise ValueError('Validation resume requires the original Blender executable')
    for path,sha in old_report['build_tools_and_project'].items():
        if digest(path)!=sha:
            raise ValueError('Authoring tool/project changed: '+path)
    lock_key=paths.fingerprint()+'-'+stable_hash(paths.namespace)[:16]
    with build_lock(Path(tempfile.gettempdir())/'foundry_h3_port_locks'/lock_key):
        before=ownership.preflight()
        require_outputs(before,{row['path']:row['sha256'] for row in old_report['generated_files']})
        cache=xml_cache(prior,old_worker,paths,before)
        build_id=time.strftime('%Y%m%d-%H%M%S')+'-validate-'+uuid.uuid4().hex[:8]
        run=ownership.directory/'runs'/build_id
        run.mkdir()
        for name in ('environment.plan.json','source-semantic-resolution.json','source-dependencies.json',
                     'unsupported-semantics.json','accepted-snapshot-inputs.json'):
            if (prior/name).is_file():shutil.copy2(prior/name,run/name)
        config=dict(old_config,plan=str(run/'environment.plan.json'),run_directory=str(run),
                    validation_only=True,expected_outputs=before,native_xml_cache=cache,
                    previous_worker_report=str(prior/'worker-report.json'),
                    previous_worker_sha256=digest(prior/'worker-report.json'))
        atomic_json(run/'worker-config.json',config)
        report=deepcopy(old_report)
        report.update(build_id=build_id,run_directory=str(run),status='BUILDING',engineering_success=False,
                      tool_invocations=[],failures=[],validation_only=True,
                      validation_resumed_from=dict(run=str(prior),report_sha256=digest(old_report_path),
                          prior_status=old_report['status'],prior_failure=old_report.get('failure'),
                          authoring_seconds=old_report['seconds'],native_xml_receipts_reused=len(cache)))
        report.pop('failure',None)
        report.pop('first_authoritative_failure',None)
        report['validation_compiler_source_hashes']={p.relative_to(addon).as_posix():digest(p) for p in addon.rglob('*.py')}
        commands=Commands(run,report)
        started=time.perf_counter()
        try:
            env=dict(os.environ,BLENDER_USER_CONFIG=str(run/'blender-config'),BLENDER_USER_SCRIPTS=str(run/'blender-scripts'))
            commands.run('blender-reach-worker',[blender,'--background','--factory-startup','--python-exit-code','1',
                '--python',Path(__file__).with_name('worker.py'),'--',run/'worker-config.json'],addon,env)
            worker=read(run/'worker-report.json')
            if worker['status']!='COMPLETE':raise ValueError('Native validation worker did not complete')
            require_outputs(paths.snapshot(),before)
            for identity in expected_tags(plan):
                if not paths.owned_tag(identity).is_file():raise ValueError('Required native tag is absent: '+identity)
            report.update(status='GENERATED',engineering_success=True)
            (ownership.directory/(report['report_prefix']+'_init_snippet.txt')).write_text(
                'game_start '+paths.scenario.replace('/','\\')+'\n',encoding='ascii')
        except Exception as exc:
            report.update(status='FAILED',failure=str(exc))
            report['failures'].append(dict(message=str(exc),traceback=traceback.format_exc()))
        finally:
            report['validation_resume_seconds']=time.perf_counter()-started
            report['seconds']=old_report['seconds']+report['validation_resume_seconds']
            if (run/'worker-report.json').is_file():
                report['worker']=read(run/'worker-report.json')
                report['tool_invocations'].extend(report['worker']['tool_invocations'])
                if report['worker'].get('failure'):report['first_authoritative_failure']=report['worker']['failure']
            after=paths.snapshot()
            if after!=before:
                report.update(status='FAILED',engineering_success=False,failure='Native output changed during read-only validation')
            else:
                ownership.save(report['status'],before,build_id)
            finish_stage_timings(report)
            cleanup_dependencies(run)
            report['disposable_dependency_cleanup']='COMPLETE'
            write_summary(run,report)
            write_summary(ownership.directory,report)
        print(report['status']+': '+str(run/(report['report_prefix']+'_build_report.md')),flush=True)
        return 0 if report['status']=='GENERATED' else 1

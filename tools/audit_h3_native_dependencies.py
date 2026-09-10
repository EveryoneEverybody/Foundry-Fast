"""Read-only native dependency closure from an owned H3-port scenario."""
import argparse
from collections import deque
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment import object_worker,worker
from port_environment.paths import OutputPaths,atomic_json,digest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('h3-root','reach-root','namespace','output'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    paths=OutputPaths(args.h3_root,args.reach_root,args.namespace,allow_nested=True)
    run=Path(args.output).resolve()
    if run.exists() or run.is_relative_to(paths.h3) or run.is_relative_to(paths.reach):raise ValueError('Use a new report folder outside both kits')
    run.mkdir(parents=True)
    report=dict(status='READING',tags=[],references=[],failures=[],optional_placeholders=[],runtime_status='NOT_TESTED',
        scope='Follow all generated tag references reachable from the scenario; check target defaults exist without traversing stock gameplay')
    object_worker.bootstrap(paths,run,report);worker.protect_tag_writes(paths,read_only=True)
    from io_scene_foundry.managed_blam import Tag
    queue=deque([paths.scenario+'.scenario']);seen=set()
    while queue:
        identity=queue.popleft()
        if identity in seen:continue
        seen.add(identity);file=paths.owned_tag(identity)
        try:
            with Tag(path=identity,tag_must_exist=True) as tag:
                for field in tag.tag.SelectTagFieldReferencesFast():
                    if field.Path is None:continue
                    name=str(field.Path.RelativePathWithExtension).replace('\\','/')
                    target=Path(str(field.Path.Filename)).resolve()
                    row=dict(owner=identity,field=str(field.FieldPath),reference=name)
                    if not target.is_relative_to(paths.roots['tags']):
                        report['failures'].append(dict(row,reason='Foreign reference'));continue
                    generated=any(ns and name.startswith(ns+'/') for ns in (paths.namespace,paths.infrastructure_namespace))
                    if not target.is_file():
                        optional=False
                        if identity.endswith('.model') and name==identity.rsplit('.',1)[0]+'.imposter_model':
                            policy=tag.tag.SelectField('imposter policy')
                            optional=str(policy.Items[policy.Value].EnumName)=='never'
                        elif identity.endswith('.scenario_structure_bsp') and name==identity.rsplit('.',1)[0]+'.instance_imposter_definition':
                            instances=tag.tag.SelectField('instanced geometry instances').Elements
                            optional=all(str(e.SelectField('imposter policy').Items[e.SelectField('imposter policy').Value].EnumName)=='never' for e in instances)
                        if optional:report['optional_placeholders'].append(dict(row,reason='Unused Tool imposter reference; native policy never or zero instances'))
                        else:report['failures'].append(dict(row,reason='Missing native dependency'))
                        continue
                    if name.startswith('levels/') and not generated:
                        report['failures'].append(dict(row,reason='Unexpected stock environment dependency'));continue
                    report['references'].append(dict(row,classification='GENERATED' if generated else 'TARGET_DEFAULT'))
                    if generated:queue.append(name)
            report['tags'].append(dict(path=identity,sha256=digest(file),status='MANAGEDBLAM_OPENED'))
        except Exception as exc:report['failures'].append(dict(owner=identity,reason=str(exc)))
        if len(seen)%100==0:
            print(f'Native dependency readback: {len(seen)} tags',flush=True)
            atomic_json(run/'report.json',report)
    report.update(status='FAILED' if report['failures'] else 'VERIFIED_REACHABLE_GENERATED_DEPENDENCIES',
        tag_count=len(report['tags']),reference_count=len(report['references']),failure_count=len(report['failures']))
    atomic_json(run/'report.json',report)
    print(json.dumps({k:report[k] for k in ('status','tag_count','reference_count','failure_count')}),flush=True)
    return bool(report['failures'])


if __name__=='__main__':
    if main():raise RuntimeError('Native dependency closure has unresolved failures; see report')

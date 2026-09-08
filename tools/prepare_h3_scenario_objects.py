"""Prepare shared native object plans, with independent per-object deferrals."""
import argparse
from collections import Counter
from copy import deepcopy
from pathlib import Path
import sys

from prepare_h3_full_scenario import read,sealed_copy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment import model,semantics,object_ir
from port_environment.paths import atomic_json,digest,relative


def merge_materials(base,extra,base_dir,extra_dir,output,needed):
    result={k:deepcopy(v) for k,v in base.items() if k not in {'shaders','bitmaps','environment_dependencies','timings','cache'}}
    result['shaders']={s:deepcopy(base['shaders'].get(s,extra['shaders'].get(s))) for s in needed}
    keys={p['bitmap'] for s in result['shaders'].values() for p in s.get('parameters',[]) if p.get('bitmap')}
    result['bitmaps']={}
    for manifest,directory,prefix in [(extra,extra_dir,'objects'),(base,base_dir,'environment')]:
        for key,source in manifest['bitmaps'].items():
            if key not in keys:continue
            row=deepcopy(source)
            for field in ('dds','preview','tiff'):
                if row.get(field):
                    dest=output/prefix/relative(row[field]);sealed_copy(directory/relative(row[field]),dest)
                    row[field]=dest.relative_to(output).as_posix()
            if row.get('cube_source'):
                dest=output/prefix/relative(row['cube_source']['tiff'])
                sealed_copy(directory/relative(row['cube_source']['tiff']),dest)
                row['cube_source']['tiff']=dest.relative_to(output).as_posix()
            result['bitmaps'][key]=row
    return result


def material(source,shader,manifest,namespace):
    errors=[];decisions=[];bits={}
    categories=semantics.options(shader)
    decal=(shader.get('group')=='rmd ' and categories.get('albedo')=='diffuse_only'
        and categories.get('blend_mode') in {'opaque','alpha_blend','multiply'}
        and categories.get('render_pass')=='pre_lighting' and categories.get('specular') in {'leave','modulate'}
        and categories.get('bump_mapping')=='leave' and categories.get('tinting')=='none')
    if shader.get('status')!='resolved_snapshot' or shader.get('group')!='rmsh' and not decal:
        errors.append('Source shader group needs its own native adapter: '+str(shader.get('group')))
    runtime=[p['name'] for p in shader.get('parameters',[]) if p.get('has_functions') or p.get('extern')]
    if runtime:
        authored={p['name']:p for p in shader.get('authored_parameters',[])}
        channels=[]
        for p in shader.get('parameters',[]):
            if p['name'] not in runtime:continue
            result=semantics.parameter_plan(p,authored.get(p['name'],{}),categories)
            functions=authored.get(p['name'],{}).get('functions',[])
            if (result['still_blocking'] and shader.get('group')=='rmsh'
                and p['name'] in {'self_illum_intensity','self_illum_color'} and not p.get('extern')
                and semantics.finite(p.get('value')) and functions
                and all(semantics.function_header(f)['type'] in {1,2,3,8} for f in functions)):
                result=semantics.decision('material.canonical_animation','STATICIZED_MVP',dict(source_parameter=p,
                    source_functions=functions,target_value=p['value'],canonical_state='Pinned source decoder time/input 0',
                    scope='Object visible emission only; no opacity, collision, device state or BSP lighting changes'),
                    loss=['Object emission animation and button indicator modulation deferred; source initial emission retained'])
            channels.append(result)
        classification=max((r['resolution_class'] for r in channels),key=semantics.CLASSES.index)
        decision=semantics.decision('material.parameters',classification,dict(parameters=channels),
            loss=[v for r in channels for v in r['fidelity_loss']])
        decisions.append(decision)
        if decision['still_blocking']:
            errors.append('Source shader has unresolved runtime functions/externs; retained in material decision')
    for param in shader.get('parameters',[]):
        key=param.get('bitmap')
        if not key:continue
        bitmap=manifest['bitmaps'].get(key)
        if bitmap is None:
            errors.append('Source bitmap absent: '+key);continue
        try:bits[key]=model.bitmap_strategy(bitmap)
        except ValueError as exc:
            decision=semantics.cube_plan(bitmap,[dict(source_shader=source,parameter=param['name'])])
            if decision['still_blocking']:errors.append('Source bitmap unsupported: '+key+'; '+str(exc))
            else:bits[key]=decision['target_authoring_plan']
    row=dict(source_shader=source,source_parameters=shader.get('parameters',[]),source_categories=shader.get('categories',[]),
        destination=namespace+'/shaders/'+Path(source).stem+'_'+model.stable_hash(source)[:8]+'.shader',
        strategy='Shared canonical H3 material -> normal ReachStager and native shader/bitmap compilation',
        semantic_authoring=decisions,classification='NATIVE_REBUILD')
    if decal:
        row['destination']=row['destination'].removesuffix('.shader')+'.shader_decal'
        decisions.append(dict(semantic_rule_id='object.material_decal',resolution_class='NATIVE_REBUILD',still_blocking=False,
            target_authoring_plan=dict(target_node='foundry_reach.shader_decal',options=categories,
                parameters={p['name']:p for p in shader.get('parameters',[])}),
            evidence=['Foundry ShaderDecalTag named native options; actual Reach RMD option names required during write/readback'],
            fidelity_loss=[]))
    return row,bits,errors


def prepare(args):
    objects=read(args.objects)['objects'];env=read(args.environment_plan)
    base_dir=Path(env['source_validation_basis']['source_run'])/'materials'
    extra_dir=Path(args.additional_materials).resolve(strict=True)
    output=Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):raise ValueError('Choose a new empty object plan directory')
    output.mkdir(parents=True,exist_ok=True);materials_dir=output/'materials';materials_dir.mkdir()
    needed=sorted({s for o in objects if o['status']=='SOURCE_DECODED' for s in o['object_ir']['materials']})
    merged=merge_materials(read(base_dir/'authoring-shader-manifest.json'),read(extra_dir/'shader_manifest.json'),
        base_dir,extra_dir,materials_dir,needed)
    results={s:material(s,merged['shaders'][s],merged,env['target']['namespace']) for s in needed}
    shader_errors={s:r[2] for s,r in results.items() if r[2]}
    rows=[]
    for source in objects:
        row=deepcopy(source);problems=[]
        if source['status']!='SOURCE_DECODED':
            problems.append(source['reason'])
        else:
            if digest(source['asset'])!=source['asset_sha256']:raise ValueError('Decoded object geometry changed')
            asset=read(source['asset']);ir=source['object_ir']
            for shader in ir['materials']:
                problems += [shader+': '+p for p in shader_errors.get(shader,[])]
            physics=asset.get('physics')
            if source['source_group']=='crate' and (not physics or not physics['shapes']):
                problems.append('Crate has no decoded native rigid-body authoring shapes')
            if physics and any(physics.get(k,0) for k in ('capsules_in_source','ragdolls_in_source','hinges_in_source')):
                problems.append('Physics includes capsule/constraint authoring outside the current bounded rigid-shape adapter')
            if physics and physics['shape_space']!='node_local':problems.append('Physics shape space is unverified')
            constraints=[r['name'] for r in ir.get('physics_authoring',[]) if r.get('count',0) and
                any(n in r['name'] for n in ('constraint','motor','powered chains'))]
            if constraints:problems.append('Physics constraint/motor authoring is deferred: '+', '.join(constraints))
            stem=Path(source['source_tag']).stem+'_'+model.stable_hash(source['source_tag'])[:12]
            target=env['target']['namespace']+'/objects/'+stem+'/'+stem
            row.update(target_base=target,target_tag=target+'.'+source['source_group'])
            animated=source['source_group'] in {'device_machine','device_control'} and bool(ir.get('animation_graph'))
            row['animation_policy']='SOURCE_DEVICE_JMA_TO_NATIVE_GRAPH' if animated else 'STATIC_SOURCE_REST_POSE'
            if ir.get('animation_graph') and not animated:
                row['fidelity_loss']=['Non-device animation graph deferred; author source model rest pose']
        row.update(native_status='NOT_GENERATED',plan_status='DEFERRED' if problems else 'READY_FOR_NATIVE',
            classification='BLOCKING_UNKNOWN' if problems else 'NATIVE_REBUILD',blockers=problems)
        rows.append(row)
    used={s for r in rows if not r['blockers'] for s in r['object_ir']['materials']}
    selected={s:results[s][0] for s in sorted(used)}
    bitmaps={k:v for s in selected for k,v in results[s][1].items()}
    manifest=dict(merged,shaders={s:merged['shaders'][s] for s in selected},bitmaps={k:merged['bitmaps'][k] for k in bitmaps})
    atomic_json(materials_dir/'authoring-shader-manifest.json',manifest)
    atomic_json(output/'material-decisions.json',{s:dict(plan=r[0],errors=r[2]) for s,r in results.items()})
    plan=dict(format='foundry.h3-scenario-native-objects',version=2,target=env['target'],objects=rows,
        materials=list(selected.values()),bitmaps=bitmaps,source_directory=str(materials_dir),
        environment_plan=str(Path(args.environment_plan).resolve()),environment_plan_sha256=digest(args.environment_plan),
        source_files={str(p):digest(p) for p in [Path(args.objects),*materials_dir.rglob('*')] if p.is_file()},
        runtime_status='NOT_TESTED')
    plan['plan_sha256']=model.stable_hash(plan)
    atomic_json(output/'objects.plan.json',plan,compact=True)
    print(dict(objects=len(rows),ready=sum(not r['blockers'] for r in rows),deferred=sum(bool(r['blockers']) for r in rows),
        shaders=len(selected),bitmaps=len(bitmaps),families=dict(Counter(r['source_group'] for r in rows if not r['blockers']))),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('objects','environment-plan','additional-materials','output'):parser.add_argument('--'+name,required=True)
    prepare(parser.parse_args())

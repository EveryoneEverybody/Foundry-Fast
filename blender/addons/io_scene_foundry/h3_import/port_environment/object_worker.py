"""Normal Foundry non-unit object authoring, isolated in a background worker."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys
import time
import tomllib
import traceback
from types import SimpleNamespace

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent));__package__='port_environment'
from . import worker,object_ir,native_object_tags
from .paths import OutputPaths,atomic_json,digest,relative
from .model import stable_hash
from .snapshot import verify_files


def bootstrap(paths,run,report):
    addon=Path(__file__).resolve().parents[2]
    report['bundled_dependencies']=worker.dependencies(addon,run)
    sys.path.insert(0,str(addon.parent))
    import bpy
    from io_scene_foundry import startup,utils,managed_blam,foundry_output
    loader=startup.load_projects;startup.load_projects=lambda:[]
    try:bpy.ops.preferences.addon_enable(module='io_scene_foundry')
    finally:startup.load_projects=loader
    version=tomllib.loads((addon/'blender_manifest.toml').read_text())['version']
    if utils.module is None:utils.module=SimpleNamespace(bl_info={'version':tuple(int(v) for v in version.split('.'))})
    prefs=utils.get_prefs();prefs.projects.clear();project=prefs.projects.add()
    project.name='H3 Full Scenario Object Worker';project.project_path=str(paths.reach)
    project.project_xml=str(paths.reach/'project.xml');project.tags_directory=str(paths.roots['tags']);project.data_directory=str(paths.roots['data'])
    project.corinth=False;prefs.tool_type='tool';prefs.link_resource_nodes=False
    foundry_output.child_stream=lambda:sys.stdout
    worker.setup_scene(paths.asset,'scenario',paths.scenario+'.sidecar.xml','default',project.name)
    os.chdir(paths.reach);managed_blam.mb_init()
    if not managed_blam.mb_active:raise RuntimeError('Reach ManagedBlam did not initialize')
    worker.protect_tag_writes(paths)
    return project.name


def construct(row,payload,scene,mats,animations,report):
    import bpy
    from io_scene_foundry import utils
    from io_scene_foundry.h3_import.builder import BuildSession
    from io_scene_foundry.h3_import.core import shader_candidates
    session=BuildSession(bpy.context,payload,row['asset'],reference_only=False,source_axes=True,emit_warnings=False)
    for _ in session.build():pass
    for mat in session.render_materials:
        candidates=shader_candidates(mat['h3_source_name'],payload['shader_paths'])
        if len(candidates)!=1 or candidates[0] not in mats:raise ValueError('Native render material identity unresolved')
        for ob in scene.objects:
            if ob.type=='MESH':
                for slot in ob.material_slots:
                    if slot.material==mat:slot.material=mats[candidates[0]]
    physics_materials=object_ir.field(row['object_ir'].get('physics_authoring',[]),'materials')
    physics_materials=physics_materials.get('elements',[]) if physics_materials else []
    for collection in session.root.children:
        if collection.name.startswith('Physics References'):
            collection.nwo.type='none'
    for ob in scene.objects:
        if ob.type!='MESH':continue
        if ob.get('h3_physics_source'):
            shape=json.loads(ob['h3_physics_source'])
            from .native_physics import shape_region_permutation
            region,permutation=shape_region_permutation(row['object_ir']['physics_authoring'],shape,payload)
            nwo=utils.get_scene_props()
            for table,name in ((nwo.regions_table,region),(nwo.permutations_table,permutation)):
                if name not in {e.name for e in table}:table.add().name=name
            ob.nwo.region_name=region;ob.nwo.permutation_name=permutation
            ob.data.nwo.mesh_type='_connected_geometry_mesh_type_physics'
            ob.nwo.rigid_body_type='LEGACY'
            ob.nwo.mesh_primitive_type='_connected_geometry_primitive_type_'+{'box':'box','sphere':'sphere','convex':'none'}[shape['kind']]
            if not 0<=shape['material']<len(physics_materials):raise ValueError('Physics material identity is absent')
            material=physics_materials[shape['material']]['fields']
            name=object_ir.scalar(object_ir.field(material,'name'))
            if not name:raise ValueError('Source physics material has no identity')
            ob.nwo.global_material=name
            report.setdefault('physics_authoring',[]).append(dict(source_shape=shape,global_material=name,
                rebuild='Normal Foundry physics mesh -> Reach Tool; native rigid-body mass/inertia required during readback'))
        elif ob.data.nwo.mesh_type=='_connected_geometry_mesh_type_collision':
            for mat in ob.data.materials:
                if mat:
                    prop=mat.nwo.material_props.add();prop.type='global_material';prop.global_material=mat['h3_source_name']
    if row['animation_policy']=='SOURCE_DEVICE_JMA_TO_NATIVE_GRAPH':
        if session.armature is None:raise ValueError('Animated device has no source skeleton')
        graph=row['object_ir']['animation_graph']
        match=next((a for a in animations if a['graph']==graph and a['exit_code']==0),None)
        if match is None:raise ValueError('Source device animation graph was not decoded')
        directory=Path(match['output']);receipt=json.loads((directory/'animation-decode-report.json').read_text())
        verify_files(receipt['source_hashes'])
        if receipt['skipped'] or receipt['written']!=receipt['source_animation_count']:raise ValueError('Source device animation decode is incomplete')
        files=sorted(p for p in directory.rglob('*') if p.is_file() and p.suffix.lower() in {'.jmm','.jma','.jmt','.jmz','.jmv','.jmw','.jmo','.jmr','.jmrx'})
        if len(files)!=receipt['written']:raise ValueError('Source device animation file count differs')
        from io_scene_foundry.legacy.jma import JMA
        source_clips=[]
        for file in files:
            clip=JMA();clip.from_file(file)
            if clip.fps!=30 or clip.frame_count<2:raise ValueError('Device JMA timing needs a separate native resampling adapter')
            source_clips.append(dict(name=file.stem,jma_frames=clip.frame_count,native_frames=clip.frame_count-1,fps=clip.fps,
                frame_convention='Pinned blam-tags JMA writer adds one reference/end frame for native Tool reimport'))
        scene.render.fps=30;scene.render.fps_base=1.0
        from io_scene_foundry.tools.importer import NWOImporter
        importer=NWOImporter(bpy.context)
        importer.import_jma_files(files,session.armature)
        report['animation_authoring']=dict(source_graph=graph,files={str(p):digest(p) for p in files},
            imported_names=[a.name for a in utils.get_scene_props().animations],frame_count=[a.frame_end-a.frame_start+1 for a in utils.get_scene_props().animations],
            source_clips=source_clips,scene_fps=30)
    report['source_construction_warnings']=session.warnings
    report['source_object_count']=len(scene.objects)
    return session


def main():
    config=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
    plan=json.loads(Path(config['plan']).read_text());run=Path(config['run_directory'])
    if stable_hash({k:v for k,v in plan.items() if k!='plan_sha256'})!=plan['plan_sha256']:raise ValueError('Object plan integrity mismatch')
    verify_files(plan['source_files'])
    paths=OutputPaths(config['h3_root'],config['reach_root'],plan['target']['namespace'],allow_nested=True)
    if paths.fingerprint()!=plan['target']['project_fingerprint']:raise ValueError('Wrong Reach project')
    report=dict(format='foundry.h3-native-object-worker',status='BUILDING',stage='bootstrap',objects=[],tool_invocations=[],geometry=[],runtime_status='NOT_TESTED')
    flush=lambda:atomic_json(run/'worker-report.json',report)
    journal=None
    try:
        flush();project=bootstrap(paths,run,report)
        journal=worker.ToolJournal(paths,run,report,flush)
        ready=[r for r in plan['objects'] if r['plan_status']=='READY_FOR_NATIVE']
        ready.sort(key=lambda r:(0 if r['target_base'].split('/')[-1].startswith('voi_switch_') else
            1 if r['source_tag'].endswith('voi_door_arms_new.device_machine') else 2,r['source_tag']))
        if config.get('limit'):ready=ready[:config['limit']]
        if config.get('reuse_compiled_from'):
            if digest(config['reuse_compiled_from'])!=config['reuse_receipt_sha256']:raise ValueError('Prior native receipt changed')
            receipt=json.loads(Path(config['reuse_compiled_from']).read_text())
            previous={r['source_tag']:r for r in receipt['worker']['objects']}
            selected=set(config.get('retry_sources') or [s for s,r in previous.items() if r['status']!='NATIVE_COMPILED'])
            report['objects']=[dict(r,reused_from=config['reuse_compiled_from']) for s,r in previous.items() if s not in selected]
            ready=[r for r in ready if r['source_tag'] in selected]
            report['receipt_reuse']=dict(path=config['reuse_compiled_from'],sha256=config['reuse_receipt_sha256'],
                verified_output_files=config['reuse_verified_output_files'],retried_sources=sorted(selected))
        report['stage']='materials';flush()
        material_config=dict(config,source_directory=plan['source_directory'],shader_manifest='authoring-shader-manifest.json',defer_material_failures=True)
        material_plan=plan
        if config.get('limit') or config.get('reuse_compiled_from'):
            used={s for r in ready for s in r['object_ir']['materials']}
            rows=[r for r in plan['materials'] if r['source_shader'] in used]
            keys={p['bitmap'] for r in rows for p in r['source_parameters'] if p.get('bitmap')}
            material_plan=dict(plan,materials=rows,bitmaps={k:plan['bitmaps'][k] for k in keys})
            source=Path(plan['source_directory']);dest=run/'selected-materials';dest.mkdir()
            manifest=json.loads((source/'authoring-shader-manifest.json').read_text())
            manifest.update(shaders={s:manifest['shaders'][s] for s in used},bitmaps={k:manifest['bitmaps'][k] for k in keys})
            for b in material_plan['bitmaps'].values():
                name=b.get('source_image') or b['source_layout']['tiff'];path=relative(name)
                target=dest/path;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source/path,target)
            atomic_json(dest/'authoring-shader-manifest.json',manifest)
            material_config['source_directory']=str(dest)
            report['material_selection']=dict(parent_plan_sha256=plan['plan_sha256'],source_shaders=sorted(used),bitmap_keys=sorted(keys),
                scope='Exact dependency subset of the hash-verified object plan')
        mats=worker.materials(material_plan,material_config,paths,report)
        animations=json.loads(Path(config['device_animations']).read_text())
        import bpy
        from io_scene_foundry import utils
        anchor=bpy.context.scene
        for index,row in enumerate(ready):
            result=dict(source_tag=row['source_tag'],source_group=row['source_group'],target_tag=row['target_tag'],status='BUILDING',runtime_status='NOT_TESTED')
            report['objects'].append(result);report['stage']='object '+row['source_tag'];flush()
            print(f'Object {index+1}/{len(ready)}: {row["source_tag"]}',flush=True)
            start=time.monotonic();tool_start=len(report['tool_invocations'])
            sys.stdout.flush();log_offset=(run/'blender-reach-worker.log').stat().st_size
            collections=('objects','meshes','armatures','collections','actions','scenes')
            previous={name:set(getattr(bpy.data,name)) for name in collections}
            try:
                missing=[s for s in row['object_ir']['materials'] if s not in mats]
                if missing:
                    errors=[e for e in report.get('material_errors',[]) if e['source'] in missing]
                    raise ValueError('Native material dependencies deferred: '+json.dumps(errors or missing))
                verify_files(row['source_hashes'])
                if digest(row['asset'])!=row['asset_sha256']:raise ValueError('Source object geometry changed')
                from io_scene_foundry.h3_import.core import load_payload
                payload=load_payload(row['asset'])
                name=Path(row['target_base']).name;directory=row['target_base'].rsplit('/',1)[0]
                scene=worker.setup_scene(name,'model',row['target_base']+'.sidecar.xml','default',project)
                nwo=utils.get_scene_props()
                for kind in ('scenery','crate','device_machine','device_control','biped','vehicle','weapon','equipment','giant','creature','effect_scenery','sound_scenery'):
                    if hasattr(nwo,'output_'+kind):setattr(nwo,'output_'+kind,kind==row['source_group'])
                utils.get_export_props().export_animations='ALL'
                utils.get_export_props().import_force=True
                construct(row,payload,scene,mats,animations,result)
                worker.export(scene,paths,directory,name,report)
                journal.finish(wait=True)
                if any(t.get('exit_code')!=0 for t in report['tool_invocations'][tool_start:]):raise ValueError('Native object Tool import failed')
                sys.stdout.flush()
                with (run/'blender-reach-worker.log').open('rb') as log:
                    log.seek(log_offset);output=log.read().decode('utf-8',errors='replace')
                result['geometry_tool_errors']=worker.geometry_errors(output)
                if result['geometry_tool_errors']:raise ValueError('Native geometry diagnostics: '+str(result['geometry_tool_errors']))
                result['tag_authoring']=native_object_tags.author(row,payload)
                result['native_validation']=native_object_tags.validate(row,payload,result.get('animation_authoring'))
                xml=run/(f'object-{index:03}-'+name+'.xml')
                utils.run_tool(['export-tag-to-xml',str(paths.owned_tag(row['target_tag'])),str(xml)],force_tool=True)
                journal.finish(wait=True)
                if not xml.is_file():raise ValueError('Native object Tool XML readback failed')
                result.update(status='NATIVE_COMPILED',tool_xml=str(xml),tool_xml_sha256=digest(xml))
            except Exception as exc:
                result.update(status='DEFERRED',reason=str(exc),traceback=traceback.format_exc())
                traceback.print_exc()
            finally:
                bpy.context.window.scene=anchor
                for name in collections:
                    data=getattr(bpy.data,name)
                    for item in set(data)-previous[name]:data.remove(item,do_unlink=True)
            result['seconds']=time.monotonic()-start;flush()
        report['status']='COMPLETE'
    except Exception as exc:
        report.update(status='FAILED',failure=str(exc),traceback=traceback.format_exc());traceback.print_exc()
    finally:
        if journal:journal.finish(wait=True)
        flush()
    if report['status']!='COMPLETE':raise RuntimeError(report['failure'])


if __name__=='__main__':main()

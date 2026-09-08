"""Normal Foundry non-unit object authoring, isolated in a background worker."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time
import tomllib
import traceback
from types import SimpleNamespace

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent));__package__='port_environment'
from . import worker,object_ir,native_object_tags
from .paths import OutputPaths,atomic_json,digest
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
            ob.data.nwo.mesh_type='_connected_geometry_mesh_type_physics'
            ob.nwo.rigid_body_type='LEGACY'
            ob.nwo.mesh_primitive_type='_connected_geometry_primitive_type_'+{'box':'box','sphere':'sphere','convex':'none'}[shape['kind']]
            if not 0<=shape['material']<len(physics_materials):raise ValueError('Physics material identity is absent')
            material=physics_materials[shape['material']]['fields']
            name=object_ir.scalar(object_ir.field(material,'global material name')) or 'default'
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
        from io_scene_foundry.tools.importer import NWOImporter
        importer=NWOImporter(bpy.context)
        importer.import_jma_files(files,session.armature)
        report['animation_authoring']=dict(source_graph=graph,files={str(p):digest(p) for p in files},
            imported_names=[a.name for a in utils.get_scene_props().animations],frame_count=[a.frame_end-a.frame_start+1 for a in utils.get_scene_props().animations])
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
        report['stage']='materials';flush()
        material_config=dict(config,source_directory=plan['source_directory'],shader_manifest='authoring-shader-manifest.json')
        mats=worker.materials(plan,material_config,paths,report)
        animations=json.loads(Path(config['device_animations']).read_text())
        import bpy
        from io_scene_foundry import utils
        ready=[r for r in plan['objects'] if r['plan_status']=='READY_FOR_NATIVE']
        # Verify the reusable source pair before the larger prop batch.
        ready.sort(key=lambda r:(0 if r['target_base'].split('/')[-1].startswith('voi_switch_') else
            1 if r['source_tag'].endswith('voi_door_arms_new.device_machine') else 2,r['source_tag']))
        if config.get('limit'):ready=ready[:config['limit']]
        for index,row in enumerate(ready):
            result=dict(source_tag=row['source_tag'],source_group=row['source_group'],target_tag=row['target_tag'],status='BUILDING',runtime_status='NOT_TESTED')
            report['objects'].append(result);report['stage']='object '+row['source_tag'];flush()
            print(f'Object {index+1}/{len(ready)}: {row["source_tag"]}',flush=True)
            start=time.monotonic();tool_start=len(report['tool_invocations'])
            try:
                verify_files(row['source_hashes'])
                if digest(row['asset'])!=row['asset_sha256']:raise ValueError('Source object geometry changed')
                payload=json.loads(Path(row['asset']).read_text())
                name=Path(row['target_base']).name;directory=row['target_base'].rsplit('/',1)[0]
                scene=worker.setup_scene(name,'model',row['target_base']+'.sidecar.xml','default',project)
                nwo=utils.get_scene_props()
                for kind in ('scenery','crate','device_machine','device_control','biped','vehicle','weapon','equipment','giant','creature','effect_scenery','sound_scenery'):
                    if hasattr(nwo,'output_'+kind):setattr(nwo,'output_'+kind,kind==row['source_group'])
                utils.get_export_props().export_animations='ALL'
                construct(row,payload,scene,mats,animations,result)
                worker.export(scene,paths,directory,name,report)
                journal.finish(wait=True)
                if any(t.get('exit_code')!=0 for t in report['tool_invocations'][tool_start:]):raise ValueError('Native object Tool import failed')
                result['tag_authoring']=native_object_tags.author(row,payload)
                result['native_validation']=native_object_tags.validate(row,payload)
                xml=run/(f'object-{index:03}-'+name+'.xml')
                utils.run_tool(['export-tag-to-xml',str(paths.owned_tag(row['target_tag'])),str(xml)],force_tool=True)
                journal.finish(wait=True)
                if not xml.is_file():raise ValueError('Native object Tool XML readback failed')
                result.update(status='NATIVE_COMPILED',tool_xml=str(xml),tool_xml_sha256=digest(xml))
            except Exception as exc:
                result.update(status='DEFERRED',reason=str(exc),traceback=traceback.format_exc())
                traceback.print_exc()
            result['seconds']=time.monotonic()-start;flush()
        report['status']='COMPLETE'
    except Exception as exc:
        report.update(status='FAILED',failure=str(exc),traceback=traceback.format_exc());traceback.print_exc()
    finally:
        if journal:journal.finish(wait=True)
        flush()
    if report['status']!='COMPLETE':raise RuntimeError(report['failure'])


if __name__=='__main__':main()

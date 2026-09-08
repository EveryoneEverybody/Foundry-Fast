"""Narrow, hash-guarded sky rebuild using the environment compiler backend.

Run inside background Blender. No BSP import, material export or Faux job is
permitted. The current scenario is backed up and only its sky reference changes.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import time
from types import SimpleNamespace


def main(config):
    addon=Path(config['addon']).resolve()
    sys.path[:0]=[str(addon.parent),str(addon/'h3_import')]
    from port_environment import fixtures,sky_attributes,snapshot,worker,native_world
    from port_environment.model import stable_hash
    from port_environment.paths import OutputPaths,Ownership,digest,atomic_json,build_lock
    from port_environment.runtime_bake import require_parent
    run=Path(config['run']).resolve()
    paths=OutputPaths(config['h3_root'],config['reach_root'],config['namespace'],allow_nested=True)
    ownership=Ownership(paths,run)
    if run.exists():
        raise ValueError('Use a new sky stabilization run directory')
    run.mkdir(parents=True)
    report=dict(format='foundry.h3-environment.sky-stabilization',version=1,status='PREFLIGHT',
        geometry=[],tool_invocations=[],runtime_status='PENDING_NATE',bsp_imported=False,faux_run=False,
        parent_manifest=str(config['parent_manifest']))
    def flush():atomic_json(run/'runtime-sky-report.json',report)
    original=json.loads(Path(config['parent_manifest']).read_text())
    if (original['namespace']!=paths.namespace or original['project_fingerprint']!=paths.fingerprint()
            or original['status']!='GENERATED'):
        raise ValueError('Parent ownership target differs')
    before=paths.snapshot()
    scenario_key='tags/'+paths.scenario+'.scenario'
    expected=dict(original['files'])
    if config.get('preserved_scenario_sha256'):
        expected[scenario_key]=config['preserved_scenario_sha256']
    preserved=config.get('preserved_external_files',{})
    require_parent(before,expected,preserved)
    report['preserved_external_files']=preserved
    report['before']=before
    report['preserved_scenario_edit']=dict(before=before[scenario_key],packaged=original['files'][scenario_key])
    plan,_,receipt=snapshot.load(config['accepted_plan'],paths,'levels/solo/040_voi/040_voi.scenario','intro_faa')
    source_run=Path(receipt['source_run'])
    report['source_snapshot']=receipt
    if len(plan['skies'])!=1:
        raise ValueError('This stabilization runner requires one selected source sky')
    sky=plan['skies'][0]
    xml=source_run/f'sky-{sky["source_index"]}-render.xml'
    if str(xml) not in receipt['verified_files']:
        # 1.9.49's sealed plan did not include the full sky XML. This is an
        # explicit, hash-pinned evidence extension, bound to the unchanged
        # original H3 sky tag and checked against every accepted triangle.
        if digest(xml)!=config.get('sky_source_xml_sha256'):
            raise ValueError('Sky attribute evidence hash differs')
        source_tag=paths.h3/'tags'/sky['source_render_model']
        if digest(source_tag)!=plan['source']['hashes'][sky['source_render_model']]:
            raise ValueError('Installed sky differs from the accepted source hash')
        report['source_attribute_evidence_extension']=dict(xml=str(xml),sha256=digest(xml),
            source_tag=str(source_tag),source_sha256=digest(source_tag),
            classification='ORIGINAL_SKY_HASH_VERIFIED; ACCEPTED_TRIANGLES_CHECKED')
    sky['mesh']=sky_attributes.recover(sky['mesh'],fixtures.parse(xml.read_bytes()))
    report['source_sky_xml']=dict(path=str(xml),sha256=digest(xml))
    report['source_sky_render_model']=sky['source_render_model']
    report['source_attribute_recovery']=sky['mesh']['source_attribute_recovery']
    report['source_draw_groups']=sky['mesh']['source_draw_groups']
    # Deliver a separate sealed plan so replaying the next full build cannot
    # lose the recovered attributes. The accepted parent file is immutable.
    plan.setdefault('source_attribute_extensions', []).append(dict(
        parent_plan_sha256=plan['plan_sha256'], source_render_model=sky['source_render_model'],
        source_xml=str(xml), source_xml_sha256=digest(xml),
        strategy=report['source_attribute_recovery']['strategy']))
    plan['source_validation_basis']['input_sha256'][str(xml)]=digest(xml)
    plan['plan_sha256']=stable_hash({k:v for k,v in plan.items() if k!='plan_sha256'})
    atomic_json(run/'environment.plan.json',plan)
    report['derived_plan']=dict(path=str(run/'environment.plan.json'),plan_sha256=plan['plan_sha256'])
    sky_directory=sky['destination'].rsplit('/',1)[0]
    allowed_prefixes=('data/'+sky_directory+'/', 'tags/'+sky_directory+'/')
    for key,sha in before.items():
        if key==scenario_key or key.startswith(allowed_prefixes) or key in preserved:
            destination=run/'before'/key
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(paths.reach/key,destination)
            if digest(destination)!=sha:raise ValueError('Stabilization backup hash mismatch')
    atomic_json(run/'recovered-sky-mesh.json',sky['mesh'])
    ownership.save('PRESERVED',expected,run.name)
    require_parent(paths.snapshot(),expected,preserved)
    flush()
    worker.dependencies(addon,run)
    import bpy
    bpy.ops.preferences.addon_enable(module='io_scene_foundry')
    from io_scene_foundry import utils,managed_blam
    from io_scene_foundry.managed_blam import Tag
    from io_scene_foundry.managed_blam.scenario import ScenarioTag
    utils.module=SimpleNamespace(bl_info={'version':(1,9,49)})
    prefs=utils.get_prefs();prefs.projects.clear();project=prefs.projects.add();project.name='H3 sky stabilization'
    project.project_path=str(paths.reach);project.project_xml=str(paths.reach/'project.xml')
    project.tags_directory=str(paths.roots['tags']);project.data_directory=str(paths.roots['data']);project.corinth=False
    name=Path(sky['destination']).stem
    scene=worker.setup_scene(name,'sky',sky_directory+'/'+name+'.sidecar.xml','default',project.name)
    os.chdir(paths.reach);managed_blam.mb_init();worker.protect_tag_writes(paths)
    journal=worker.ToolJournal(paths,run,report,flush)
    base_check=journal.check
    def check(command):
        command=base_check(command)
        if command[1]=='import' and command[2].replace('\\','/')!=sky_directory+'/'+name+'.sidecar.xml':
            raise ValueError('Sky stabilization cannot import another asset')
        if command[1] not in {'import','export-tag-to-xml'}:
            raise ValueError('Sky stabilization cannot run '+command[1])
        return command
    journal.check=check
    with build_lock(run):
        ownership.save('BUILDING',expected,run.name)
        report['status']='BUILDING';flush()
        mats={}
        for material in plan['materials']:
            if material['source_shader'] not in sky['materials']:continue
            ob=bpy.data.materials.new(material['source_shader'].rsplit('/',1)[-1])
            ob.nwo.shader_path=material['destination']
            if not paths.owned_tag(material['destination']).is_file():raise ValueError('Missing owned sky shader')
            mats[material['source_shader']]=ob
        worker.construct_sky(scene,sky,mats,report)
        view=dict(plan,sky=sky,lighting=dict(plan['lighting'],sky=sky['lighting']))
        worker.sky_lights(scene,view)
        utils.get_export_props().import_force=True
        worker.export(scene,paths,sky_directory,name,report)
        worker.configure_sky_model(view)
        journal.finish(wait=True)
        if any(row.get('exit_code')!=0 for row in report['tool_invocations']):raise RuntimeError('Sky Tool import failed')
        with ScenarioTag(path=paths.scenario+'.scenario',tag_must_exist=True) as tag:
            if tag.block_skies.Elements.Count!=1:raise ValueError('Scenario sky palette changed')
            field=tag.block_skies.Elements[0].SelectField('sky')
            report['scenario_sky_reference_before']=str(field.Path.RelativePathWithExtension)
            field.Path=tag._TagPath_from_string(sky['destination'])
            tag.tag.Save()
        native_world.validate(plan,report)
        target_xml=run/'native-sky.render_model.xml'
        utils.run_tool(['export-tag-to-xml', str(paths.owned_tag(sky['destination'].rsplit('.',1)[0]+'.render_model')),
            str(target_xml)], force_tool_fast=True)
        journal.finish(wait=True)
        if any(row.get('exit_code')!=0 for row in report['tool_invocations']):
            raise RuntimeError('Sky Tool readback failed')
        report['native_color_readback']=sky_attributes.native_color_readback(
            fixtures.parse(xml.read_bytes()),fixtures.parse(target_xml.read_bytes()),report['source_draw_groups'])
        with Tag(path=sky['destination'].rsplit('.',1)[0]+'.render_model',tag_must_exist=True) as tag:
            region_names=[r.SelectField('name').GetStringData() for r in tag.tag.SelectField('Block:regions').Elements]
            if region_names!=[r['region_name'] for r in report['source_draw_groups']]:
                raise ValueError('Native sky region order differs from source')
            report['native_sky_regions']=region_names
            report['native_color_meshes']=[]
            for i,m in enumerate(tag.tag.SelectField('Struct:render geometry[0]/Block:meshes').Elements):
                flags=m.SelectField('mesh flags')
                report['native_color_meshes'].append(dict(index=i,has_vertex_color=flags.TestBit('mesh has vertex color')))
        after=paths.snapshot()
        if any(after.get(k)!=sha for k,sha in preserved.items()):
            raise ValueError('A preserved external file changed during sky export')
        changed={k:dict(before=before.get(k),after=after.get(k)) for k in sorted(before.keys()|after.keys()) if before.get(k)!=after.get(k)}
        if any(k!=scenario_key and not k.startswith(allowed_prefixes) for k in changed):
            raise ValueError('Sky stabilization unexpectedly changed another environment resource')
        report.update(status='GENERATED_PENDING_RUNTIME',changed_files=changed,after=after,
            preserved_non_sky_outputs=sum(k!=scenario_key and not k.startswith(allowed_prefixes) for k in before))
        ownership.save('GENERATED',{k:v for k,v in after.items() if k not in preserved},run.name)
        flush()
    print('SKY_STABILIZATION_COMPLETE',run)


if __name__=='__main__':
    args=sys.argv[sys.argv.index('--')+1:]
    main(json.loads(Path(args[0]).read_text(encoding='utf-8-sig')))

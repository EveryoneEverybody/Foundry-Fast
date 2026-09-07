"""Reference frames, deterministic child instances and semantic sources persist."""
import copy
import importlib
import json
from pathlib import Path
import runpy
import tempfile
import bpy
from mathutils import Vector

base=runpy.run_path(str(Path(__file__).with_name('blender_h3_scenario_smoke.py')))
from h3_scenario_content_fixture import content_inventory
from h3_scenario_fixture import scene, Fields
from h3_import_fixture import payload
Session=base['mod'].ScenarioBuildSession

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory); data=content_inventory(); assets={}
    for extension in ('scenery','device_machine','crate','weapon'):
        model=payload(); model['source_tag']='objects/test/panel.'+extension; model['physics']=None
        model['default_variant']='default'
        model['variants']=[dict(name='default',regions=[],children=[])]
        if extension=='scenery':
            model['variants'][0]['children']=[dict(source_tag='objects/test/panel.weapon',variant='default',parent_marker='attach',child_marker='',source_fields=[])]
        path=root/(extension+'.h3asset.json');path.write_text(json.dumps(model))
        assets[model['source_tag']]=dict(status='extracted',asset=str(path))
    # Semantic fixtures exercise the same detached helper result consumed in real imports.
    fields=Fields();fields.ordinals['']=800
    for category,extension,group in [('sound scenery','sound_scenery','ssce'),('light volumes','light','ligh')]:
        pal=fields.element(fields.block('',category+' palette'))
        fields.add(pal,'name',dict(path='objects/test/reference',extension=extension))
        ob=fields.element(fields.block('',category));fields.add(ob,'name',-1);fields.add(ob,'type',0)
        datum=fields.add(ob,'object data',kind='struct',field_type='struct')
        fields.point(datum,'position',[2,3,4]);fields.point(datum,'rotation',[0,0,0]);fields.point(datum,'scale',[1])
        source='objects/test/reference.'+extension;path=root/(extension+'.json')
        path.write_text(json.dumps(dict(format='foundry.h3-semantic',version=1,game='halo3_mcc',source_tag=source,
            group=group,destination_tags_written=False,records=[dict(address='/type#0',name='type',value={'value':0,'name':'source type'})])))
        assets[source]=dict(status='semantic',semantic=str(path))
    # One explicit frame refers to the first scenario placement by full object id.
    first=next(r['address'] for r in data['records'] if r['name']=='object data')
    oid=fields.add(first,'object id',kind='struct',field_type='struct')
    frame=fields.element(fields.block('','reference frames'))
    frame_id=fields.add(frame,'object id',kind='struct',field_type='struct')
    for parent in (oid,frame_id):
        for key,value in [('unique id',123),('origin bsp index',-1),('type',{'value':6}),('source',{'value':1})]:fields.add(parent,key,value)
    fields.add(frame,'node index',0);fields.add(frame,'projection axis',0);fields.add(frame,'flags',{'value':0})
    start=next(r for r in data['records'] if r['name']=='reference frame' and r['address'].startswith('squads'))
    start['value']=0
    data['records'].extend(fields.rows)
    source_before=copy.deepcopy(data)
    context=scene();context['bsp_entries']=[]
    before=base['count']()
    session=Session(bpy.context,context,data,root,import_objects=True,import_content=True,object_assets=assets,preview_materials=False)
    list(session.steps());bpy.context.view_layer.update()
    assert data==source_before
    parent=next(o for o in session.root.all_objects if o.name=='gate_a')
    other=next(o for o in session.root.all_objects if o.name=='gate_b')
    assert parent.instance_collection is other.instance_collection
    children=[o for o in parent.instance_collection.objects if o.get('h3_source_role')=='child_attachment']
    assert len(children)==1
    child=children[0]
    assert (child.matrix_world.translation-Vector((160,200,0))*session.scale).length<1e-5
    assert child.instance_collection and not child.nwo.export_this
    assert json.loads(child['h3_source_attachment'])['source_index']==0
    semantic=[o for o in session.root.all_objects if o.get('h3_source_role')=='semantic_reference']
    assert len(semantic)==2 and all(o['h3_semantic_source'] in bpy.data.texts for o in semantic)
    assert not any('Unsupported object group' in w or 'no supported model' in w for w in session.warnings)
    start=next(o for o in session.root.all_objects if o.get('h3_source_role')=='squad starts')
    row=json.loads(start['h3_source_content'])
    assert row['reference_frame']==0 and row['source_position']==[1,2,3]
    expected=session.rotation @ (Vector(row['position'])*100*session.scale)
    assert (start.matrix_world.translation-expected).length<1e-4
    report=json.loads(bpy.data.texts[session.root['h3_reference_frame_report']].as_string())
    assert '0' in report['resolved']
    # Full rollback, including child templates and semantic Text records.
    session.rollback();assert base['count']()==before
    # Cancellation while a nested child builder owns a partial armature must
    # close that builder and roll back already completed parent resources.
    session=Session(bpy.context,context,data,root,import_objects=True,import_content=True,object_assets=assets,preview_materials=False)
    steps=session.steps();cancelled=False
    for stage in steps:
        if 'Object template objects/test/panel.weapon: Skeleton' in stage:
            cancelled=True;break
    assert cancelled
    steps.close();session.rollback();assert base['count']()==before
    session=Session(bpy.context,context,data,root,import_objects=True,import_content=True,object_assets=assets,preview_materials=False)
    list(session.steps());name=session.root.name
    path=str(root/'references.blend');bpy.ops.wm.save_as_mainfile(filepath=path)
    for asset in assets.values():Path(asset.get('asset',asset.get('semantic'))).unlink()
    bpy.ops.wm.open_mainfile(filepath=path)
    parent=next(o for o in bpy.data.collections[name].all_objects if o.name=='gate_a')
    child=next(o for o in parent.instance_collection.objects if o.get('h3_source_role')=='child_attachment')
    assert child.instance_collection.all_objects and child['h3_source_attachment']
    assert all(o['h3_semantic_source'] in bpy.data.texts for o in bpy.data.collections[name].all_objects if o.get('h3_source_role')=='semantic_reference')
print('H3 reference tests passed: object/node frames, child marker transform, cache reuse, semantic sound/light, rollback and save/reopen')

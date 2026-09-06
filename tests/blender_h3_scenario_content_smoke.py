"""Actual existing object construction, reuse, source transforms and cancellation."""
import copy
import json
from pathlib import Path
import runpy
import tempfile
import bpy
from mathutils import Euler, Matrix, Vector

base=runpy.run_path(str(Path(__file__).with_name('blender_h3_scenario_smoke.py')))
from h3_scenario_content_fixture import content_inventory
from h3_import_fixture import payload
from h3_scenario_fixture import scene
Session=base['mod'].ScenarioBuildSession
count=base['count']

with tempfile.TemporaryDirectory() as d:
    directory=Path(d);assets={}
    for extension in ('scenery','device_machine','crate'):
        data=payload();data['source_tag']='objects/test/panel.'+extension;data['physics']=None
        data['variants']=[dict(name=name,regions=[dict(name='body',parent_variant=-1,permutations=[dict(name=name)])]) for name in ('default','alternate')]
        path=directory/(extension+'.h3asset.json');path.write_text(json.dumps(data))
        assets[data['source_tag']]=dict(status='extracted',asset=str(path))
    data=scene();data['bsp_entries']=[]
    for units,forward in [('blender','x'),('blender','y'),('max','x')]:
        bpy.context.scene.nwo.scale=units;bpy.context.scene.nwo.forward_direction=forward
        base['base']['settings'].scale=units;base['base']['settings'].forward_direction=forward
        before=count()
        session=Session(bpy.context,data,content_inventory(),directory,import_objects=True,import_content=True,object_assets=assets,preview_materials=False)
        stages=list(session.steps());bpy.context.view_layer.update()
        assert session.counts['placed_objects']==6 and session.counts['placed_placeholders']==0,session.warnings
        assert session.counts['object_templates']==4,session.counts
        placed={o.name:o for o in session.root.all_objects if o.get('h3_source_role')=='placed_object'}
        assert placed['gate_a'].instance_collection is placed['gate_b'].instance_collection
        assert placed['gate_a'].instance_collection is not placed['gate_variant'].instance_collection
        assert placed['machine_a'].instance_collection is placed['machine_b'].instance_collection
        assert placed['crate_a'].instance_collection is not placed['machine_a'].instance_collection
        for name in ('gate_a','gate_variant'):
            template=placed[name].instance_collection
            render=[o for o in template.all_objects if o.name.startswith('render:')]
            assert len(render)==1,[o.name for o in render]
            assert all(not o.nwo.export_this for o in template.all_objects)
            assert template.name not in bpy.context.scene.collection.children
        ob=placed['gate_b']
        expected=session.rotation @ Matrix.LocRotScale(Vector((11,20,30))*100*session.scale,Euler((-.1,-.25,.5),'ZYX').to_quaternion(),Vector((2,2,2)))
        assert max(abs(ob.matrix_world[r][c]-expected[r][c]) for r in range(4) for c in range(4))<1e-4
        assert not ob.nwo.export_this and ob['h3_source_variant']=='default'
        assert json.loads(ob['h3_source_placement'])['metadata']['permutation']['active change colors']['value']==1
        props=session.content_groups['folder:1'];assert props.name.startswith('Props')
        assert props in list(session.content_groups['folder:0'].children)
        assert placed['gate_a'].users_collection[0] in list(props.children)
        fp=next(o for o in session.root.all_objects if o.get('h3_source_role')=='firing_positions')
        assert fp.users_collection[0] is session.content_groups['zone:0/area:0']
        point=next(o for o in session.root.all_objects if o.get('h3_source_role')=='script_points')
        assert point.users_collection[0] is session.content_groups['point-set:0:0']
        trigger=next(o for o in session.root.all_objects if o.get('h3_source_role')=='trigger volumes')
        assert len(trigger.data.splines)==12 and trigger.hide_render
        session.rollback();assert count()==before,(count(),before)
    # Cancel while the nested normal object builder owns partial resources.
    before=count();session=Session(bpy.context,data,content_inventory(),directory,import_objects=True,object_assets=assets,preview_materials=False)
    steps=session.steps()
    for stage in steps:
        if 'Skeleton' in stage:break
    steps.close();session.rollback();assert count()==before,(count(),before)
    # Cached collection references survive save/reopen, including source metadata.
    session=Session(bpy.context,data,content_inventory(),directory,import_objects=True,import_content=True,object_assets=assets,preview_materials=False)
    list(session.steps());root_name=session.root.name
    path=str(directory/'content.blend');bpy.ops.wm.save_as_mainfile(filepath=path)
    for row in assets.values():Path(row['asset']).unlink()
    bpy.ops.wm.open_mainfile(filepath=path)
    placed={o.name:o for o in bpy.data.collections[root_name].all_objects if o.get('h3_source_role')=='placed_object'}
    assert placed['gate_a'].instance_collection is placed['gate_b'].instance_collection
    assert placed['gate_a'].instance_collection.all_objects
print('H3 scenario content passed: reused normal object importer, variants, transforms, folders, metadata, overlays, export exclusion, cancellation, save/reopen')

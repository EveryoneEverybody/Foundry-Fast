"""Synthetic BSP and authored-hint construction. No real H3EK or Reach export."""
import base64
import copy
import importlib
import json
from pathlib import Path
import runpy
import shutil
import tempfile

import bpy
from mathutils import Matrix, Vector

base = runpy.run_path(str(Path(__file__).with_name('blender_h3_import_smoke.py')))
from h3_scenario_fixture import BSP, SCENARIO, bsp, instance, write_bundle
from h3_material_fixture import manifest

class ScenarioObjectProps(bpy.types.PropertyGroup):
    export_this: bpy.props.BoolProperty(default=True)
    node_order_source: bpy.props.StringProperty()
    marker_type: bpy.props.StringProperty()

class ScenarioMaterialProps(bpy.types.PropertyGroup):
    shader_path: bpy.props.StringProperty()

class ScenarioSceneProps(bpy.types.PropertyGroup):
    scale: bpy.props.StringProperty(default='blender')
    forward_direction: bpy.props.StringProperty(default='x')

for cls in (ScenarioObjectProps, ScenarioMaterialProps, ScenarioSceneProps):
    bpy.utils.register_class(cls)
del bpy.types.Object.nwo
bpy.types.Object.nwo = bpy.props.PointerProperty(type=ScenarioObjectProps)
bpy.types.Material.nwo = bpy.props.PointerProperty(type=ScenarioMaterialProps)
bpy.types.Scene.nwo = bpy.props.PointerProperty(type=ScenarioSceneProps)
mod = importlib.import_module(base['NAME'] + '.h3_import.scenario_builder')
source = importlib.import_module(base['NAME'] + '.h3_import.scenario_scene')


def count():
    return tuple(len(store) for store in (bpy.data.collections, bpy.data.objects, bpy.data.meshes,
        bpy.data.curves, bpy.data.materials, bpy.data.images, bpy.data.armatures, bpy.data.texts))


def near(a, b):
    assert (Vector(a) - Vector(b)).length < 1e-4, (a, b)


def write_bsp(root, data):
    (root / 'geometry/bsp_0000.json').write_text(json.dumps(data), encoding='utf-8')


def shaders(root):
    (root / 'textures').mkdir(exist_ok=True)
    image = bpy.data.images.new('scene fixture', width=2, height=2, alpha=True)
    image.pixels[:] = [1., .5, .5, 1.] * 4
    image.filepath_raw = str(root / 'textures/00000.tif')
    image.file_format = 'TIFF'
    image.save()
    bpy.data.images.remove(image)
    data = manifest()
    data['source_tag'] = SCENARIO
    second = copy.deepcopy(data['shaders']['objects/test/test.shader'])
    second['source'] = 'other/test.shader'
    second['parameters'][0]['transform'] = [4., 5., .1, .2]
    data['shaders']['other/test.shader'] = second
    return data


def imported(root):
    return list(root.all_objects)


for units, forward in [('blender', 'x'), ('blender', 'y'), ('max', 'x')]:
    bpy.context.scene.nwo.scale = units
    bpy.context.scene.nwo.forward_direction = forward
    with tempfile.TemporaryDirectory() as d:
        directory = Path(d)
        write_bundle(directory, with_blob=True)
        data, inventory = source.load_scene(directory / 'scene.h3scene.json', SCENARIO)
        material_manifest = shaders(directory)
        before = count()
        session = mod.ScenarioBuildSession(bpy.context, data, inventory, directory, material_manifest)
        assert list(session.steps())[-1] == 'Scenario reference complete'
        bpy.context.view_layer.update()
        root = session.root
        assert root.nwo.type == 'exclude'
        objects = imported(root)
        assert all(not ob.nwo.export_this for ob in objects)
        assert all(c.nwo.type == 'exclude' for c in bpy.data.collections if c.get('h3_reference_only'))
        assert len(bpy.data.armatures) == before[6]
        meshes = [ob for ob in objects if ob.type == 'MESH']
        assert len(meshes) == 2 and meshes[0].data is meshes[1].data
        assert all(not ob.hide_render for ob in meshes)
        assert session.counts == dict(bsp_meshes=1, bsp_placements=2, sectors=1, rails=1, firing_positions=1, script_points=1)
        mesh = meshes[0].data
        scale = .03048 if units == 'blender' else 1.
        near(mesh.vertices[1].co, [100*scale, 0, 0])
        by_id = {json.loads(ob['h3_source_instance'])['id']: ob for ob in meshes}
        near(by_id[1].matrix_world @ mesh.vertices[0].co, session.rotation @ Vector([100*scale,0,0]))
        near(by_id[2].matrix_world @ mesh.vertices[1].co, session.rotation @ Vector([0,0,0]))
        assert by_id[2].matrix_world.determinant() < 0
        assert mesh.polygons[0].material_index == 1
        assert mesh.attributes['h3_source_material_slot'].data[0].value == 1
        near(mesh.corner_normals[0].vector, [0,.6,.8])
        near(mesh.attributes['h3_source_normal'].data[0].vector, [0,.6,.8])
        assert len(mesh.uv_layers) == 2
        near(mesh.uv_layers[1].data[1].uv, [2,0])
        assert mesh.attributes['h3_uv_w_0'].data[2].value == 5
        assert mesh.attributes['h3_uv_w_1'].data[2].value == 7
        near(mesh.color_attributes['Color'].data[0].color, [.1,.3,.7,1])
        mats = list(mesh.materials)
        assert mats[0] is not mats[1] and all(m.nwo.shader_path == '' for m in mats)
        assert all(m.use_nodes for m in mats), session.preview.results
        scales = [next(n for n in m.node_tree.nodes if n.label == 'base_map scale').inputs[1].default_value[:2] for m in mats]
        assert tuple(scales[0]) == (2,3) and tuple(scales[1]) == (4,5)
        image_nodes = [next(n for n in m.node_tree.nodes if n.type == 'TEX_IMAGE' and n.label == 'base_map') for m in mats]
        assert image_nodes[0].image is image_nodes[1].image
        assert all(image.packed_file for image in session.preview.images.values())
        sector = next(o for o in objects if o.get('h3_source_role') == 'sectors')
        spline = sector.data.splines[0]
        assert spline.type == 'POLY' and spline.use_cyclic_u and len(spline.points) == 3
        near(spline.points[1].co[:3], session.rotation @ Vector([200*scale,0,0]))
        rail = next(o for o in objects if o.get('h3_source_role') == 'rails')
        assert not rail.data.splines[0].use_cyclic_u
        assert json.loads(rail['h3_source_hint'])['geometry_index'] == 0
        assert all(o.hide_render for o in objects if o.type != 'MESH')
        assert json.loads(bpy.data.texts[root['h3_shader_manifest']].as_string()) == material_manifest
        assert json.loads(bpy.data.texts[root['h3_scenario_manifest']].as_string()) == inventory
        packed = json.loads(bpy.data.texts[root['h3_packed_data']].as_string())
        assert base64.b64decode(bpy.data.texts[packed[0]['text']].as_string()) == b'\x00\x01\xfe\xff'
        second = mod.ScenarioBuildSession(bpy.context, data, inventory, directory)
        list(second.steps())
        assert second.root is not root
        second.rollback()
        assert len(imported(root)) == len(objects)
        session.rollback()
        assert count() == before, (count(), before)
        session.rollback()
        assert count() == before

# Parent rotation and scale compose before the geometry-only pivot.
with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    data, inventory = write_bundle(root)
    geometry = bsp()
    geometry['instances'] = [instance(2,0,1,[100,0,0],pivot_position=[0,50,0]),
                             instance(1,-1,0,[100,0,0],rotation=[.70710678118,0,0,.70710678118],scale=2),
                             instance(0,-1)]
    write_bsp(root,geometry)
    before = count()
    session = mod.ScenarioBuildSession(bpy.context,data,inventory,root)
    list(session.steps());bpy.context.view_layer.update()
    ob = next(o for o in imported(session.root) if o.type == 'MESH')
    near(ob.matrix_world.translation,[0,200,0])
    near(ob.matrix_world @ ob.data.vertices[1].co,[0,400,0])
    session.rollback();assert count() == before
    geometry['instances'][-1]['inheritance_flag'] = 1
    write_bsp(root,geometry)
    session = mod.ScenarioBuildSession(bpy.context,data,inventory,root)
    list(session.steps())
    assert not any(o.type == 'MESH' for o in imported(session.root))
    assert any('inheritance' in warning for warning in session.warnings)
    session.rollback();assert count() == before

# Xrefs are placeholders, not invented geometry. Auxiliary geometry stays hidden.
with tempfile.TemporaryDirectory() as d:
    root = Path(d);data, inventory = write_bundle(root)
    geometry=bsp();geometry['objects'].append(copy.deepcopy(geometry['objects'][0]))
    geometry['objects'][1]['id']=1;geometry['objects'][1]['xref_path']='objects/external/external.scenery'
    geometry['instances'].extend([instance(3,1,0),instance(4,0,0,name='+portal_0')])
    write_bsp(root,geometry);before=count()
    session=mod.ScenarioBuildSession(bpy.context,data,inventory,root)
    list(session.steps());bpy.context.view_layer.update()
    ob=next(o for o in imported(session.root) if o.get('h3_source_definition') == 1)
    assert ob.type=='EMPTY' and ob.hide_get() and ob.hide_render
    portal=next(o for o in imported(session.root) if o.name=='+portal_0')
    assert portal.hide_get() and portal.hide_render
    session.rollback();assert count()==before

# A late failure removes earlier BSP content rather than leaving a partial asset.
with tempfile.TemporaryDirectory() as d:
    root=Path(d);data,inventory=write_bundle(root,with_blob=True);before=count()
    (root/'blobs/000000.bin').write_bytes(b'changed')
    session=mod.ScenarioBuildSession(bpy.context,data,inventory,root)
    try:
        list(session.steps());raise AssertionError('Changed blob accepted')
    except ValueError:
        session.rollback()
    assert count()==before

# Save/reopen retains geometry, source records, blobs, and packed material images.
with tempfile.TemporaryDirectory() as d:
    output=Path(d);root=output/'extraction';root.mkdir()
    data,inventory=write_bundle(root,with_blob=True)
    session=mod.ScenarioBuildSession(bpy.context,data,inventory,root,shaders(root))
    list(session.steps());name=session.root.name
    shutil.rmtree(root)
    blend=str(output/'scene.blend')
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    bpy.ops.wm.open_mainfile(filepath=blend)
    root=bpy.data.collections[name]
    assert root.nwo.type=='exclude' and not any(o.nwo.export_this for o in root.all_objects)
    assert sum(o.type=='MESH' for o in root.all_objects)==2
    assert json.loads(bpy.data.texts[root['h3_scenario_manifest']].as_string())==inventory
    packed=json.loads(bpy.data.texts[root['h3_packed_data']].as_string())
    assert base64.b64decode(bpy.data.texts[packed[0]['text']].as_string())==b'\x00\x01\xfe\xff'
    images=[n.image for o in root.all_objects if o.type=='MESH' for m in o.data.materials for n in m.node_tree.nodes if n.type=='TEX_IMAGE']
    assert images and all(i.packed_file for i in images)
print('H3 scenario synthetic Blender tests passed: geometry, materials, hints, transforms, exclusions, rollback, persistence')

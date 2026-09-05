"""Exercise the bundled Reach shader group, not a substitute test group."""
import copy
import importlib
import json
from pathlib import Path
import runpy
import tempfile
import bpy

base = runpy.run_path(str(Path(__file__).with_name('blender_h3_import_smoke.py')))
from h3_illumination_fixture import manifest, SHADER, MAP, DETAIL
module = importlib.import_module(base['NAME'] + '.h3_import.reach_builder')
ops = importlib.import_module(base['NAME'] + '.h3_import.reach_ops')

class MaterialProps(bpy.types.PropertyGroup):
    shader_type: bpy.props.StringProperty()
    shader_path: bpy.props.StringProperty()
    uses_blender_nodes: bpy.props.BoolProperty()

class ImageProps(bpy.types.PropertyGroup):
    filepath: bpy.props.StringProperty()
    source_name: bpy.props.StringProperty()
    bitmap_type: bpy.props.StringProperty()
    reexport_tiff: bpy.props.BoolProperty()

for cls in (MaterialProps, ImageProps):
    bpy.utils.register_class(cls)
bpy.types.Material.nwo = bpy.props.PointerProperty(type=MaterialProps)
bpy.types.Image.nwo = bpy.props.PointerProperty(type=ImageProps)


def load_resource(blend, name):
    group = bpy.data.node_groups.get(name)
    if group is None:
        path = base['ROOT'] / 'blends' / (blend + '.blend')
        with bpy.data.libraries.load(str(path), link=False) as (source, target):
            assert name in source.node_groups, (name, source.node_groups)
            target.node_groups = [name]
        group = bpy.data.node_groups[name]
    return group


def no_aliases(selected, cache):
    return {}, []


def build_source(data, name='source'):
    text = bpy.data.texts.new('H3 shader source - ' + name)
    text.write(json.dumps(data))
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material['h3_source_shader'] = SHADER
    material['h3_source_object'] = data['source_tag']
    material['h3_shader_manifest'] = text.name
    for key, bitmap in data['bitmaps'].items():
        image = bpy.data.images.new(name + key, width=4, height=4, alpha=True)
        image.pixels[:] = [0.2, 0.3, 0.4, 0.5] * 16
        image['h3_source_bitmap'] = bitmap['path']
        image['h3_bitmap_index'] = bitmap['index']
        image.colorspace_settings.name = 'Non-Color'
        image.nwo.filepath = 'must_not_change.tif'
        image.pack()
        tex = material.node_tree.nodes.new('ShaderNodeTexImage'); tex.image = image
    return material


def group_of(material):
    return next(n for n in material.node_tree.nodes if n.type == 'GROUP' and n.node_tree.name == 'foundry_reach.shader')


def source_snapshot(material):
    return ([(n.name, n.type) for n in material.node_tree.nodes],
            [(n.image.name, n.image.colorspace_settings.name, n.image.nwo.filepath)
             for n in material.node_tree.nodes if n.type == 'TEX_IMAGE'],
            bpy.data.texts[material['h3_shader_manifest']].as_string())


data = manifest()
source = build_source(data)
snapshot = source_snapshot(source)
stager = module.ReachStager(load_resource, no_aliases)
native = stager.build(source)
assert native, stager.results
print('REACH_STAGING_RESULT', json.dumps(stager.results[-1]))
group = group_of(native)
print('REACH_ACTIVE_INPUTS', [(s.name, s.type) for s in group.inputs if s.is_icon_visible])
assert group.inputs['self_illumination'].default_value == 'illum_detail'
assert group.inputs['albedo'].default_value == 'constant_color'
assert group.inputs['material_model'].default_value == 'none'
assert group.inputs['blend_mode'].default_value == 'additive'
assert native.nwo.shader_path == '' and native.nwo.uses_blender_nodes
assert native.nwo.shader_type == '.shader'
assert native['h3_source_material'] == source
assert native.surface_render_method == 'BLENDED'
for name in ('self_illum_map.rgb', 'self_illum_detail_map.rgb'):
    assert group.inputs[name].is_linked, name
    assert group.inputs[name].links[0].from_node.type == 'TEX_IMAGE'
assert tuple(group.inputs['self_illum_color'].default_value)[:3] == (1, group.inputs['self_illum_color'].default_value[1], 0)
assert abs(group.inputs['self_illum_color'].default_value[1] - 75 / 255) < 1e-6
assert group.inputs['self_illum_intensity'].default_value == 3
assert not any(n.type == 'BSDF_PRINCIPLED' for n in native.node_tree.nodes)
tiling = next(n for n in native.node_tree.nodes if n.label == 'self_illum_detail_map transform')
assert tiling.node_tree.name == 'Texture Tiling'
assert tiling.inputs['Scale X'].default_value == 2
assert source_snapshot(source) == snapshot
second = stager.build(source)
assert second != native
assert len(stager.images) == 2
second_tiling = next(n for n in second.node_tree.nodes if n.label == 'self_illum_detail_map transform')
second_tiling.inputs['Scale X'].default_value = 7
assert tiling.inputs['Scale X'].default_value == 2
assert all(i.packed_file and i.nwo.filepath == '' for i in stager.images.values())
assert all(i.nwo.bitmap_type == 'Self-Illum Map' for i in stager.images.values())

# Unsupported fields leave an editable partial material instead of blocking staging.
unknown = copy.deepcopy(data)
unknown['shaders'][SHADER]['categories'].append({'category': 'distortion', 'option': 'unavailable'})
unknown['shaders'][SHADER]['parameters'] += [
    {'name': 'scene_ldr_texture', 'type': 'bitmap', 'extern': 'texture_global_target_texaccum'},
    {'name': 'bump_detail_coefficient', 'type': 'real', 'value': 2}]
other = build_source(unknown, 'unsupported fields')
partial = stager.build(other)
assert partial, stager.results
assert any(p['status'] == 'runtime_input' for p in stager.results[-1]['parameters'])
assert any(p['name'] == 'bump_detail_coefficient' and p['status'] == 'unmapped' for p in stager.results[-1]['parameters'])

# A lit body uses the same native group with different independent input values.
body = copy.deepcopy(data)
choices = {'albedo': 'default', 'bump_mapping': 'detail', 'material_model': 'two_lobe_phong',
           'self_illumination': 'off', 'blend_mode': 'opaque'}
for c in body['shaders'][SHADER]['categories']:
    c['option'] = choices.get(c['category'], c['option'])
body['shaders'][SHADER]['parameters'] = [
    {'name': 'albedo_color', 'type': 'argb color', 'value': [.2, .4, .6, .8]},
    {'name': 'diffuse_coefficient', 'type': 'real', 'value': 0.0}]
for name, key, transform in [('base_map', MAP, [1, 1, 0, 0]), ('detail_map', MAP, [20, 20, 0, 0]),
                             ('bump_map', MAP, [1, 1, 0, 0]), ('bump_detail_map', DETAIL, [10, 10, .25, -.5])]:
    body['shaders'][SHADER]['parameters'].append({'name': name, 'type': 'bitmap', 'bitmap': key,
        'transform': transform, 'sampler': {'filter': 'point', 'address_x': 'clamp', 'address_y': 'clamp'}})
body_source = build_source(body, 'metal body')
body_native = stager.build(body_source)
assert body_native, stager.results
body_group = group_of(body_native)
assert body_group.inputs['material_model'].default_value == 'two_lobe_phong'
assert body_group.inputs['bump_map.rgb'].links[0].from_node.type == 'TEX_IMAGE'
assert body_group.inputs['bump_detail_map.rgb'].is_linked
assert abs(body_group.inputs['albedo_color_alpha'].default_value - .8) < 1e-6
assert body_group.inputs['diffuse_coefficient'].default_value == 0
tex = body_group.inputs['bump_map.rgb'].links[0].from_node
assert tex.image.colorspace_settings.name == 'Non-Color'
assert tex.image.nwo.bitmap_type == 'Normal Map (aka zbump)'
assert tex.extension == 'EXTEND' and tex.interpolation == 'Closest'
assert not any(n.type == 'NORMAL_MAP' for n in body_native.node_tree.nodes)

# Linked duplicate geometry outside the staged selection keeps its original assignments.
bpy.ops.mesh.primitive_cube_add()
ob = bpy.context.object
ob.data.materials.clear(); ob.data.materials.append(source)
external = bpy.data.objects.new('outside staging', ob.data)
bpy.context.scene.collection.objects.link(external)
geometry = [(tuple(v.co)) for v in ob.data.vertices]
assignment_stager = module.ReachStager(load_resource, no_aliases)
assert assignment_stager.apply([ob]) == 1
assert ob.active_material.get('h3_reach_staged')
assert external.active_material == source
assert [(tuple(v.co)) for v in ob.data.vertices] == geometry
assert assignment_stager.apply([ob]) == 0
assignment_stager.rollback()
assert ob.active_material == source and ob.material_slots[0].link == 'DATA'
assert source_snapshot(source) == snapshot

# Saved materials retain source identity, packed images, and editable native inputs.
with tempfile.TemporaryDirectory() as d:
    native.use_fake_user = True
    material_name = native.name
    path = str(Path(d) / 'reach_staging.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    reopened = bpy.data.materials[material_name]
    assert reopened['h3_source_material'] is not None
    assert reopened.nwo.shader_path == ''
    assert group_of(reopened).inputs['self_illum_map.rgb'].is_linked
    assert all(n.image.packed_file for n in reopened.node_tree.nodes if n.type == 'TEX_IMAGE')
print('H3 Reach staging passed: native resources, named options, textures, tiling, colors, zero scalars, normal roles, independent materials, packed images, source preservation, slot isolation, rollback and reopen')

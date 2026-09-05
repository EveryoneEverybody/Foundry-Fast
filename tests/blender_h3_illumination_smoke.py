"""Illumination graph, packing and numerical render checks with synthetic textures."""
import copy
import importlib
from pathlib import Path
import runpy
import tempfile
import bpy

base = runpy.run_path(str(Path(__file__).with_name('blender_h3_import_smoke.py')))
from h3_illumination_fixture import manifest, set_option, SHADER, MAP, DETAIL
PreviewBuilder = importlib.import_module(base['NAME'] + '.h3_import.material_builder').PreviewBuilder
materials = importlib.import_module(base['NAME'] + '.h3_import.materials')


def by_label(mat, label):
    return next(n for n in mat.node_tree.nodes if n.label == label)


def build(data, directory, session):
    owner = PreviewBuilder(data, directory, session.remember)
    mat = session.remember(bpy.data.materials, bpy.data.materials.new('Illumination smoke'))
    mat['h3_source_shader'] = SHADER
    before = copy.deepcopy(data)
    owner.build(mat)
    assert owner.results[-1]['status'] == 'approximate_preview', owner.results[-1]
    assert data == before
    assert mat['h3_source_shader'] == SHADER
    assert 'shader_path' not in mat
    return owner, mat


with tempfile.TemporaryDirectory() as folder:
    directory = Path(folder); (directory / 'textures').mkdir()
    # Zero alpha must not suppress illum_detail's RGB result.
    for number, color in enumerate([(0.1, 0.2, 0.4, 0), (0.5, 0.3, 0.8, 0)]):
        image = bpy.data.images.new('Synthetic illumination', width=4, height=4, alpha=True, float_buffer=True)
        image.colorspace_settings.name = 'Non-Color'
        image.alpha_mode = 'CHANNEL_PACKED'
        image.pixels[:] = list(color) * 16
        image.filepath_raw = str(directory / f'textures/{number:05}.tif')
        image.file_format = 'TIFF'; image.save()
        bpy.data.images.remove(image)
    session = base['BuildSession'](bpy.context, base['payload'](), 'synthetic.h3asset.json')
    data = manifest()
    owner, target = build(data, directory, session)
    emission = by_label(target, 'H3 unlit self illumination')
    assert emission.inputs['Color'].is_linked
    assert emission.inputs['Strength'].default_value == 3
    assert not any(n.type == 'BSDF_PRINCIPLED' for n in target.node_tree.nodes)
    add = by_label(target, 'Additive self illumination preview')
    assert add.inputs[0].links[0].from_node == emission
    assert add.inputs[1].links[0].from_node.type == 'BSDF_TRANSPARENT'
    output = by_label(target, 'Blender preview only')
    assert output.inputs['Surface'].links[0].from_node == add
    for name, scale in [('self_illum_map', 1), ('self_illum_detail_map', 2)]:
        tex = by_label(target, name)
        assert tex.outputs['Color'].is_linked
        assert not tex.outputs['Alpha'].is_linked
        assert tuple(by_label(target, name + ' scale').inputs[1].default_value) == (scale, scale, 1)
        assert tex.image.packed_file and tex.image.colorspace_settings.name == 'Non-Color'
    assert abs(by_label(target, 'Illum detail multiplier').inputs[1].default_value[0] - materials.DETAIL_MULTIPLIER) < 1e-5
    assert all('is not reproduced' not in d for d in owner.results[-1]['diagnostics'])
    assert any('time-zero' in d for d in owner.results[-1]['diagnostics'])

    other = session.remember(bpy.data.materials, bpy.data.materials.new('Other illumination'))
    other['h3_source_shader'] = SHADER
    parameters = {p['name']: p for p in data['shaders'][SHADER]['parameters']}
    parameters['self_illum_detail_map']['transform'] = [7, 9, .25, -.5]
    parameters['self_illum_intensity']['value'] = 1
    owner.build(other)
    assert len(owner.images) == 2
    assert target != other
    assert by_label(target, 'self_illum_map').image == by_label(other, 'self_illum_map').image
    assert tuple(by_label(other, 'self_illum_detail_map scale').inputs[1].default_value) == (7, 9, 1)
    assert tuple(by_label(target, 'self_illum_detail_map scale').inputs[1].default_value) == (2, 2, 1)
    assert emission.inputs['Strength'].default_value == 3

    for mode in sorted(materials.ILLUMINATION_MODES):
        for blend in ['opaque', 'additive']:
            case = manifest(); set_option(case, 'self_illumination', mode); set_option(case, 'blend_mode', blend)
            _, mat = build(case, directory, session)
            assert any(n.type == 'EMISSION' for n in mat.node_tree.nodes), (mode, blend)
            assert any(n.type == 'BSDF_TRANSPARENT' for n in mat.node_tree.nodes) == (blend == 'additive')
    lit = manifest(); set_option(lit, 'material_model', 'two_lobe_phong'); set_option(lit, 'blend_mode', 'opaque')
    _, mat = build(lit, directory, session)
    assert by_label(mat, 'Approximate H3 surface').inputs['Emission Color'].is_linked
    assert not any(n.type == 'ADD_SHADER' for n in mat.node_tree.nodes)
    missing = manifest(); missing['bitmaps'][DETAIL].pop('preview')
    missing_owner, mat = build(missing, directory, session)
    assert any('self_illum_detail_map:' in d for d in missing_owner.results[-1]['diagnostics'])
    assert tuple(by_label(mat, 'Illum detail multiplier').inputs[0].default_value) == (0, 0, 0)
    off = manifest(); set_option(off, 'self_illumination', 'off')
    off_owner, _ = build(off, directory, session)
    assert not any('Self illumination off' in d for d in off_owner.results[-1]['diagnostics'])
    unknown = manifest(); set_option(unknown, 'self_illumination', 'plasma')
    unknown_owner, _ = build(unknown, directory, session)
    assert any('Self illumination plasma is not reproduced' in d for d in unknown_owner.results[-1]['diagnostics'])

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    scene = bpy.context.scene
    bpy.ops.mesh.primitive_plane_add(size=4)
    plane = bpy.context.object; plane.data.materials.append(target)
    bpy.ops.object.camera_add(location=(0, 0, 2))
    camera = bpy.context.object; camera.data.type = 'ORTHO'; camera.data.ortho_scale = 2
    scene.camera = camera
    scene.world = bpy.data.worlds.new('Illumination test world'); scene.world.use_nodes = True
    background = (.05, .1, .15)
    world = scene.world.node_tree.nodes.get('Background')
    world.inputs['Color'].default_value = (*background, 1); world.inputs['Strength'].default_value = 1
    scene.render.resolution_x = scene.render.resolution_y = 32; scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'OPEN_EXR'; scene.render.image_settings.color_depth = '32'
    scene.render.film_transparent = False
    scene.view_settings.view_transform = 'Standard'
    scene.render.engine = 'CYCLES'; scene.cycles.device = 'CPU'; scene.cycles.samples = 8
    scene.cycles.use_denoising = False
    scene.cycles.max_bounces = 4; scene.cycles.transparent_max_bounces = 8
    c0 = tuple(by_label(target, 'self_illum_map').image.pixels[:3])
    c1 = tuple(by_label(target, 'self_illum_detail_map').image.pixels[:3])
    tint = (1, 75 / 255, 0)
    expected = tuple(background[i] + c0[i] * c1[i] * materials.DETAIL_MULTIPLIER * tint[i] * 3 for i in range(3))
    assert expected[0] > background[0] + .01, expected

    def render_check(engine, strength, expected_color, label):
        scene.render.engine = engine
        emission.inputs['Strength'].default_value = strength
        scene.render.filepath = str(directory / (label + '.exr'))
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(scene.render.filepath, check_existing=False)
        offset = (16 * 32 + 16) * 4
        actual = tuple(image.pixels[offset:offset + 3])
        bpy.data.images.remove(image)
        assert all(abs(a - b) < .015 for a, b in zip(actual, expected_color)), (engine, label, actual, expected_color)
        print('ILLUMINATION_RENDER', engine, label, actual, 'expected', expected_color)

    for engine in ['CYCLES', 'BLENDER_EEVEE']:
        render_check(engine, 3, expected, 'detail_' + engine)
        render_check(engine, 0, background, 'zero_' + engine)
    emission.inputs['Strength'].default_value = 3
    target.name = 'Saved illumination'
    for file in (directory / 'textures').glob('*.tif'):
        file.unlink()
    blendfile = str(directory / 'illumination.blend')
    bpy.ops.wm.save_as_mainfile(filepath=blendfile)
    bpy.ops.wm.open_mainfile(filepath=blendfile)
    saved = bpy.data.materials['Saved illumination']
    assert by_label(saved, 'self_illum_map').image.packed_file
    assert by_label(saved, 'self_illum_detail_map').image.packed_file
    assert by_label(saved, 'H3 unlit self illumination').inputs['Strength'].default_value == 3
    assert saved['h3_source_shader'] == SHADER
print('H3 illumination checks passed: active textures, RGB math, additive transmission, material separation, diagnostics, packing, Cycles and Eevee renders')

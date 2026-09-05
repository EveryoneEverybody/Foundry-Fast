"""Synthetic material preview construction and packed-image persistence."""
import copy
import importlib
from pathlib import Path
import runpy
import tempfile
import bpy

# Reuse the geometry test's minimal Foundry package and property registrations.
base = runpy.run_path(str(Path(__file__).with_name('blender_h3_import_smoke.py')))
from h3_material_fixture import manifest
PreviewBuilder = importlib.import_module(base['NAME'] + '.h3_import.material_builder').PreviewBuilder
BuildSession = base['BuildSession']

with tempfile.TemporaryDirectory() as d:
    directory = Path(d); (directory / 'textures').mkdir()
    image_path = directory / 'textures/00000.tif'
    image = bpy.data.images.new('synthetic TIFF', width=2, height=2, alpha=True)
    image.pixels[:] = [1, 0, 0, 0, 0, 1, 0, .5, 0, 0, 1, 1, .5, .5, 1, 1]
    image.filepath_raw = str(image_path); image.file_format = 'TIFF'; image.save()
    bpy.data.images.remove(image)
    before = len(bpy.data.images)
    session = BuildSession(bpy.context, base['payload'](), 'synthetic.h3asset.json')
    data = manifest()
    owner = PreviewBuilder(data, directory, session.remember, True)
    materials = []
    for mode in ('default', 'constant_color', 'detail_blend', 'two_change_color', 'four_change_color'):
        shader = data['shaders']['objects/test/test.shader']
        shader['categories'][0]['option'] = mode
        for _ in range(2):
            mat = session.remember(bpy.data.materials, bpy.data.materials.new('H3 smoke ' + mode))
            mat['h3_source_shader'] = 'objects/test/test.shader'
            owner.build(mat); materials.append(mat)
            assert owner.results[-1]['status'] == 'approximate_preview', owner.results[-1]
            assert mat['h3_source_shader'] == 'objects/test/test.shader'
    assert len(owner.images) == 2, owner.images
    assert len({m.as_pointer() for m in materials}) == 10
    assert {i.colorspace_settings.name for i in owner.images.values()} == {'Non-Color', 'sRGB'}
    assert all(i.packed_file for i in owner.images.values())
    assert all(i.alpha_mode == 'CHANNEL_PACKED' for i in owner.images.values())
    mat = materials[0]
    principled = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    assert not principled.inputs['Alpha'].is_linked
    assert principled.inputs['Normal'].is_linked
    assert any(n.label == 'Flip normal green' for n in mat.node_tree.nodes)
    scale = next(n for n in mat.node_tree.nodes if n.label == 'base_map scale')
    assert tuple(scale.inputs[1].default_value) == (2, 3, 1)
    shader['categories'].append({'category': 'alpha_test', 'option': 'on'})
    shader['categories'].append({'category': 'self_illumination', 'option': 'simple'})
    owner.build(mat)
    assert owner.results[-1]['status'] == 'approximate_preview', owner.results[-1]
    principled = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    assert principled.inputs['Alpha'].is_linked
    assert principled.inputs['Emission Color'].is_linked
    session.rollback()
    assert len(bpy.data.images) == before

    # The source files can disappear after packing without losing the saved preview.
    session = BuildSession(bpy.context, base['payload'](), 'synthetic.h3asset.json')
    owner = PreviewBuilder(manifest(), directory, session.remember, False)
    mat = session.remember(bpy.data.materials, bpy.data.materials.new('H3 packed persistence'))
    mat.use_fake_user = True; mat['h3_source_shader'] = 'objects/test/test.shader'
    owner.build(mat)
    assert owner.results[-1]['status'] == 'approximate_preview', owner.results[-1]
    assert not any(n.label == 'Flip normal green' for n in mat.node_tree.nodes)
    expected = {image.name: tuple(image.pixels[:]) for image in owner.images.values()}
    image_path.unlink()
    blend = str(directory / 'packed_test.blend')
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    bpy.ops.wm.open_mainfile(filepath=blend)
    for name, pixels in expected.items():
        image = bpy.data.images[name]
        assert image.packed_file
        assert all(abs(a-b) < .0001 for a, b in zip(image.pixels[:], pixels))
print('H3 material tests passed: nodes, UV transforms, RGBA, alpha policy, normal green, image identity, rollback, packing and reopen')

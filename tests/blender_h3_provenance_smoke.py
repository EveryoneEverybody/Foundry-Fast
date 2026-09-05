"""Synthetic whole-import checks for provenance and existing preview behavior."""
import copy
import json
from pathlib import Path
import runpy
import tempfile
import bpy

base = runpy.run_path(str(Path(__file__).with_name('blender_h3_import_smoke.py')))
from test_h3_import_material_descriptions import manifest_with_description

class TestMaterialProps(bpy.types.PropertyGroup):
    shader_path: bpy.props.StringProperty()

bpy.utils.register_class(TestMaterialProps)
bpy.types.Material.nwo = bpy.props.PointerProperty(type=TestMaterialProps)

with tempfile.TemporaryDirectory() as d:
    directory = Path(d)
    (directory / 'textures').mkdir()
    image = bpy.data.images.new('provenance fixture', width=2, height=2, alpha=True)
    image.pixels[:] = [1, .5, .5, 1] * 4
    image.filepath_raw = str(directory / 'textures/00000.tif')
    image.file_format = 'TIFF'
    image.save()
    bpy.data.images.remove(image)
    for reference_only in (True, False):
        data = base['payload']()
        paths = ['objects/test/test.shader', 'objects/test/test_tinted.shader']
        data['shader_paths'] = paths
        for i, material in enumerate(data['render']['materials']):
            material['name'] = 'test' if i == 0 else 'test_tinted'
        manifest = manifest_with_description()
        manifest['source_tag'] = data['source_tag']
        second = copy.deepcopy(manifest['shaders'][paths[0]])
        second['source'] = paths[1]
        second['source_description']['source_shader'] = paths[1]
        second['parameters'][0]['transform'][:2] = [4, 2]
        second['source_description']['parameters'][0]['texture_transform']['scale'] = [4, 2]
        manifest['shaders'][paths[1]] = second
        (directory / 'shader_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        before = base['snapshot'](), len(bpy.data.images)
        geometry = copy.deepcopy(data['render'])
        session = base['BuildSession'](bpy.context, data, directory / 'asset.h3asset.json', reference_only, True)
        assert list(session.build())[-1] == 'Complete'
        root = next(c for c in bpy.data.collections if c.get('h3_source_tag') == data['source_tag'])
        retained = json.loads(bpy.data.texts[root['h3_shader_manifest']].as_string())
        assert retained == manifest
        assert (root.nwo.type == 'exclude') == reference_only
        assert data['render'] == geometry
        assert len(bpy.data.images) - before[1] == 2
        assert len({m.as_pointer() for m in session.render_materials}) == len(session.render_materials)
        assert all(m.nwo.shader_path == '' for m in session.render_materials)
        scales = []
        for m in session.render_materials:
            scale = next(n for n in m.node_tree.nodes if n.label == 'base_map scale')
            scales.append(tuple(scale.inputs[1].default_value)[:2])
        assert scales[0] == (2, 3) and scales[1] == (4, 2)
        report = bpy.data.texts[root['h3_material_report']].as_string()
        assert 'global_options_not_merged' in report
        physics = next(o for o in bpy.data.objects if o.get('h3_physics_source'))
        assert next(iter(physics.users_collection)).nwo.type == 'exclude'
        session.rollback()
        assert (base['snapshot'](), len(bpy.data.images)) == before

# Source descriptions persist even without their extraction directory.
    text = bpy.data.texts.new('provenance persistence')
    text.use_fake_user = True
    text.write(json.dumps(manifest))
    blend = str(directory / 'provenance.blend')
    (directory / 'shader_manifest.json').unlink()
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    bpy.ops.wm.open_mainfile(filepath=blend)
    assert json.loads(bpy.data.texts['provenance persistence'].as_string()) == manifest
print('H3 provenance smoke passed: source JSON, preview transforms, image reuse, material identities, exclusions, rollback and saved metadata')

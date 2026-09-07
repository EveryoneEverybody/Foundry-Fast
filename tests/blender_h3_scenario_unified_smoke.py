"""Unified scenario adapter: pruning, native hierarchy, sky, compact points and persistence."""
import dataclasses
import importlib
import json
from pathlib import Path
import runpy
import tempfile
from unittest.mock import patch

import bpy

base = runpy.run_path(str(Path(__file__).with_name('blender_h3_scenario_smoke.py')))
from h3_scenario_content_fixture import content_inventory
from h3_import_fixture import payload
from h3_scenario_fixture import scene, Fields, write_bundle
package = base['mod'].__package__
Options = importlib.import_module(package + '.scenario_options').ScenarioOptions
assets_module = importlib.import_module(package + '.scenario_assets')
object_module = importlib.import_module(package + '.scenario_objects')
Session = base['mod'].ScenarioBuildSession
count = base['count']

# Supply the additional collection fields used by the source adapter.
class CollectionProps(bpy.types.PropertyGroup):
    type: bpy.props.StringProperty(default='none')
    region: bpy.props.StringProperty()
    permutation: bpy.props.StringProperty()
bpy.utils.register_class(CollectionProps)
del bpy.types.Collection.nwo
bpy.types.Collection.nwo = bpy.props.PointerProperty(type=CollectionProps)


def layer_for(collection):
    stack = [bpy.context.view_layer.layer_collection]
    while stack:
        layer = stack.pop()
        if layer.collection == collection: return layer
        stack.extend(layer.children)
    raise AssertionError(collection.name)


def fixture():
    inventory = content_inventory()
    f = Fields(); f.ordinals[''] = 400
    sky = f.block('', 'skies', 2)
    for i in range(2):
        p = f.element(sky, i)
        f.add(p, 'sky', dict(path='objects/test/panel', extension='scenery'), field_type='tag reference')
        f.add(p, 'active on bsps', 255)
    inventory['records'].extend(f.rows)
    return inventory


with tempfile.TemporaryDirectory() as d:
    directory = Path(d)
    write_bundle(directory)
    data = scene()
    assets = {}
    for ext in ('scenery', 'device_machine', 'crate'):
        source = payload(); source['source_tag'] = 'objects/test/panel.' + ext
        source['physics'] = None
        path = directory / (ext + '.h3asset.json'); path.write_text(json.dumps(source))
        assets[source['source_tag']] = dict(status='extracted', asset=str(path))

    before = count()
    # No optional category may invoke extraction or construct a debug datablock.
    with patch.object(object_module, 'extract', side_effect=AssertionError('disabled extraction')):
        session = Session(bpy.context, data, fixture(), directory, options=Options(), preview_materials=False)
        list(session.steps())
    assert session.counts['firing_positions'] == 0
    assert not session.inspection_groups
    assert not session.templates
    assert session.root.name.startswith('scenario_') and session.root.nwo.type == 'none'
    bsp = next(c for c in session.root.children if c.get('h3_source_bsp'))
    assert bsp.nwo.type == 'region' and bsp.nwo.region and bsp.color_tag == 'COLOR_05'
    render = next(c for c in bsp.children if c.name.startswith('Render'))
    assert render.nwo.type == 'permutation' and render.color_tag == 'COLOR_04'
    session.rollback(); assert count() == before, (before, count())

    options = Options(objects=True, sky='h3:1', ai=True, firing_positions=True, giant_hints=True, script_points=True)
    session = Session(bpy.context, data, fixture(), directory, object_assets=assets, options=options, preview_materials=False)
    list(session.steps())
    assert session.counts['placed_objects'] == 6
    assert session.counts['firing_positions'] == 1
    points = [o for o in session.root.all_objects if o.get('h3_source_role') == 'firing_positions']
    assert len(points) == 1 and points[0].type == 'MESH'
    assert len(points[0].data.vertices) == 1
    assert json.loads(bpy.data.texts[points[0]['h3_point_records']].as_string())[0]['address']
    sky = next(o for o in session.root.all_objects if o.get('h3_source_role') == 'scenario_sky')
    assert sky['h3_source_sky_index'] == 1 and not sky.hide_render and not sky.nwo.export_this
    assert not layer_for(sky.users_collection[0]).hide_viewport
    assert len(json.loads(bpy.data.texts[session.root['h3_sky_entries']].as_string())) == 2
    objects = session.content_groups['Objects']
    assert objects.name.startswith('040_test_objects') or objects.name.endswith('_objects')
    assert objects.nwo.type == 'exclude'
    assert session.content_groups['folder:0'] in list(objects.children)
    for collection in session.hidden_collections:
        assert layer_for(collection).hide_viewport and not layer_for(collection).exclude
        assert all(not ob.hide_get() for ob in collection.objects)
    assert all(not mat.nwo.shader_path for mat in bpy.data.materials if mat.get('h3_source_shader'))

    root_name = session.root.name
    hidden_names = [c.name for c in session.hidden_collections]
    save_path = str(directory / 'unified.blend')
    bpy.ops.wm.save_as_mainfile(filepath=save_path)
    # Rollback includes nested template, shared/cached resources and point metadata.
    session.rollback(); assert count() == before, (before, count())
    bpy.ops.wm.open_mainfile(filepath=save_path)
    for name in hidden_names:
        layer = layer_for(bpy.data.collections[name])
        assert layer.hide_viewport and not layer.exclude
        layer.hide_viewport = False
        assert not layer.hide_viewport
    assert bpy.data.collections[root_name]['h3_sky_entries']

print('Unified H3 scenario passed: options, source skies, BSP semantics/colors, excluded placements, compact points, visibility, rollback and save/reopen')

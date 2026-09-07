"""Unified scenario adapter: pruning, native hierarchy, sky, compact points and persistence."""
import dataclasses
import copy
import importlib
import json
from pathlib import Path
import runpy
import tempfile
import time
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


def fixture(point_count=1):
    inventory = content_inventory()
    f = Fields(); f.ordinals[''] = 400
    sky = f.block('', 'skies', 2)
    for i in range(2):
        p = f.element(sky, i)
        f.add(p, 'sky', dict(path='objects/test/panel', extension='scenery'), field_type='tag reference')
        f.add(p, 'active on bsps', 255)
    inventory['records'].extend(f.rows)
    block = next(r for r in inventory['records'] if r['name'] == 'firing positions' and r['kind'] == 'block')
    original = block['address'] + '[0]'
    children = [r for r in inventory['records'] if r['address'].startswith(original + '/')]
    block['count'] = point_count
    for i in range(1, point_count):
        for row in children:
            clone = copy.deepcopy(row)
            clone['address'] = clone['address'].replace(original, block['address'] + f'[{i}]', 1)
            inventory['records'].append(clone)
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

    # An unavailable selected sky is nonfatal and never substitutes a different sky.
    before = count()
    session = Session(bpy.context, data, fixture(), directory, object_assets={},
                      options=Options(sky='h3:1'), preview_materials=False)
    list(session.steps())
    assert not any(o.get('h3_source_role') == 'scenario_sky' for o in session.root.all_objects)
    assert session.counts['bsp_meshes'] and any('Sky 1' in w for w in session.warnings)
    session.rollback(); assert count() == before

    # Measure both representations; correctness guards use counts, never wall time.
    inventory = fixture(4612)
    benchmark = {}
    for detailed in (False, True):
        before = count(); started = time.perf_counter()
        session = Session(bpy.context, data, inventory, directory, options=Options(
            geometry=False, firing_positions=True, detailed_points=detailed), preview_materials=False)
        list(session.steps())
        points = [o for o in session.root.all_objects if o.get('h3_source_role') == 'firing_positions']
        benchmark['detailed' if detailed else 'compact'] = dict(seconds=time.perf_counter()-started,
            objects=len(points), mesh_vertices=sum(len(o.data.vertices) for o in points if o.type == 'MESH'))
        assert len(points) == (4612 if detailed else 1)
        assert session.counts['firing_positions'] == 4612
        session.rollback(); assert count() == before
    print('POINT_BENCHMARK', json.dumps(benchmark))

    # A source template's bone parenting matches the ordinary builder, without
    # one full depsgraph evaluation for every individual marker.
    class ViewLayer:
        def __init__(self): self.calls = 0
        @property
        def objects(self): return bpy.context.view_layer.objects
        def update(self):
            self.calls += 1
            bpy.context.view_layer.update()
    class Context:
        def __init__(self): self.view_layer = ViewLayer()
        def __getattr__(self, name): return getattr(bpy.context, name)
    source = payload(); source['physics'] = None
    source['render']['nodes'][1]['rotation'] = [.9238795325, 0., 0., .3826834324]
    source['render']['markers'] = [dict(source['render']['markers'][0], name=f'marker_{i}', position=[10.+i, 0., 0.]) for i in range(100)]
    settings = base['base']['settings']; settings.scale='blender'; settings.forward_direction='x'
    builds = []
    for direct in (False, True):
        context = Context()
        build = base['base']['BuildSession'](context, source, directory/'synthetic.h3asset.json', source_axes=direct)
        list(build.build()); bpy.context.view_layer.update()
        markers = {o['h3_source_marker']: o for o in build.root.all_objects if o.get('h3_source_marker')}
        builds.append((build, markers, context.view_layer.calls))
    assert builds[1][2] <= 2 and builds[0][2] >= 100, [b[2] for b in builds]
    for pose in (False, True):
        if pose:
            for build, _, _ in builds:
                build.armature.pose.bones['b_panel'].location.z += 1.
            bpy.context.view_layer.update()
        for name, marker in builds[0][1].items():
            a = marker.matrix_world; b = builds[1][1][name].matrix_world
            assert max(abs(a[r][c]-b[r][c]) for r in range(4) for c in range(4)) < 1e-4, name
    for build, _, _ in reversed(builds): build.rollback()

    # BSPs, sky and object variants share source materials and packed images.
    for asset in assets.values():
        source = json.loads(Path(asset['asset']).read_text())
        source['shader_paths'] = ['objects/test/test.shader']
        for material in source['render']['materials']: material['name'] = 'test'
        Path(asset['asset']).write_text(json.dumps(source))
    manifest = base['shaders'](directory)
    before = count()
    session = Session(bpy.context, data, fixture(), directory, material_manifest=manifest,
        object_assets=assets, options=Options(objects=True, sky='h3:0', materials=True))
    list(session.steps())
    shared = [m for m in bpy.data.materials if m.get('h3_source_shader') == 'objects/test/test.shader'
              and any(item == m for _, item in session.created if isinstance(item, bpy.types.Material))]
    assert len(shared) == 1, [m.name for m in shared]
    assert session.preview.image_hits > 0
    assert session.preview.usage and len(session.preview.materials) == 2
    assert session.counts['object_templates'] >= 3
    session.finish_profile(1.)
    assert not session.source_payloads and session.content_plan is None
    session.rollback(); assert count() == before, (before, count())
    # Late construction failure rolls back shared caches and nested templates.
    session = Session(bpy.context, data, fixture(), directory, material_manifest=manifest,
        object_assets=assets, options=Options(objects=True, sky='h3:0', materials=True))
    with patch.object(session, 'bsp_steps', side_effect=ValueError('injected BSP failure')):
        try: list(session.steps())
        except ValueError: session.rollback()
        else: raise AssertionError('Expected construction failure')
    assert count() == before, (before, count())

    # Requested categories control external work, not only final visibility.
    requests = []
    def extract_spy(content, *args, **kwargs):
        requests.append(content)
        if False: yield
        return assets
    with patch.object(object_module, 'extract', extract_spy):
        session = Session(bpy.context, data, fixture(), directory, tags_root=directory,
            object_helper=directory/'helper', options=Options(geometry=False, sky='h3:1'))
        list(session.steps())
        assert len(requests) == 1 and len(requests[0]['placements']) == 1
        assert requests[0]['placements'][0]['source_tag'] == 'objects/test/panel.scenery'
        assert session.profile.counts['sky_objects'] == 1
        session.rollback(); assert count() == before
    with patch.object(object_module, 'extract', side_effect=AssertionError('Disabled object/sky decode')), \
         patch.object(assets_module.subprocess, 'Popen', side_effect=AssertionError('Disabled shader decode')):
        session = Session(bpy.context, data, fixture(), directory, tags_root=directory,
            object_helper=directory/'helper', options=Options(geometry=False, materials=True))
        list(session.steps()); session.rollback(); assert count() == before

print('Unified H3 scenario passed: options, source skies, BSP semantics/colors, excluded placements, compact points, visibility, rollback and save/reopen')

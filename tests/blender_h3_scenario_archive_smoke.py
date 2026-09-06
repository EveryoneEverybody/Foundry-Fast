"""Exercise chunked scenario sources with real Blender datablocks and persistence."""
import base64
import copy
import importlib
import json
from pathlib import Path
import runpy
import shutil
import tempfile

import bpy

base = runpy.run_path(str(Path(__file__).with_name('blender_h3_scenario_smoke.py')))
from h3_scenario_archive_fixture import write_archive
from h3_scenario_fixture import SCENARIO, write_bundle

builder = base['mod']
source = base['source']
inspection = source.inspection
archive = importlib.import_module(inspection.__package__ + '.scenario_archive')


def restore(collection):
    manifest = json.loads(bpy.data.texts[collection['h3_scenario_manifest']].as_string())
    index = json.loads(bpy.data.texts[collection['h3_packed_inventory']].as_string())
    return archive.from_packed(manifest, index, lambda name: bpy.data.texts[name].as_string())


for units, forward in [('blender', 'x'), ('blender', 'y'), ('max', 'x')]:
    bpy.context.scene.nwo.scale = units
    bpy.context.scene.nwo.forward_direction = forward
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        _, legacy = write_bundle(root, with_blob=True)
        original = copy.deepcopy(legacy['records'])
        encoded = write_archive(root, legacy, per_chunk=2)
        scene, inventory = source.load_scene(root / 'scene.h3scene.json', SCENARIO)
        assert inventory['version'] == 2 and 'records' not in inventory
        assert list(inspection.iter_records(inventory)) == original
        before = base['count']()
        session = builder.ScenarioBuildSession(bpy.context, scene, inventory, root, base['shaders'](root))
        list(session.steps())
        bpy.context.view_layer.update()
        collection = session.root
        assert collection.nwo.type == 'exclude'
        assert all(not ob.nwo.export_this for ob in collection.all_objects)
        assert session.counts['inventory_records'] == len(original)
        assert session.counts['inventory_chunks'] == len(encoded['chunks'])
        packed_entries = json.loads(bpy.data.texts[collection['h3_packed_inventory']].as_string())
        assert all(max(map(len, bpy.data.texts[e['text']].as_string().splitlines()), default=0) <= 76 for e in packed_entries)
        assert session.counts['sectors'] == 1 and session.counts['rails'] == 1
        assert session.counts['bsp_meshes'] == 1 and session.counts['bsp_placements'] == 2
        assert source.hint_plan(restore(collection)) == source.hint_plan(legacy)
        assert list(inspection.iter_records(restore(collection))) == original
        duplicate = builder.ScenarioBuildSession(bpy.context, scene, inventory, root)
        list(duplicate.steps())
        assert duplicate.root is not collection
        assert list(inspection.iter_records(restore(duplicate.root))) == original
        duplicate.rollback()
        assert list(inspection.iter_records(restore(collection))) == original
        session.rollback()
        assert base['count']() == before

# A changed chunk after loading cannot leave a half-built reference collection.
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    _, legacy = write_bundle(root, with_blob=True)
    encoded = write_archive(root, legacy)
    scene, inventory = source.load_scene(root / 'scene.h3scene.json', SCENARIO)
    before = base['count']()
    session = builder.ScenarioBuildSession(bpy.context, scene, inventory, root)
    (root / encoded['chunks'][0]['file']).write_bytes(b'changed')
    try:
        list(session.steps())
        raise AssertionError('Changed source chunk accepted')
    except ValueError:
        session.rollback()
    assert base['count']() == before

# Query all retained records after saving, reopening and deleting every source file.
with tempfile.TemporaryDirectory() as temporary:
    output = Path(temporary)
    root = output / 'extraction'
    root.mkdir()
    _, legacy = write_bundle(root, with_blob=True)
    original = copy.deepcopy(legacy['records'])
    write_archive(root, legacy, per_chunk=2)
    scene, inventory = source.load_scene(root / 'scene.h3scene.json', SCENARIO)
    session = builder.ScenarioBuildSession(bpy.context, scene, inventory, root, base['shaders'](root))
    list(session.steps())
    name = session.root.name
    shutil.rmtree(root)
    path = str(output / 'chunked.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    collection = bpy.data.collections[name]
    retained = restore(collection)
    assert list(inspection.iter_records(retained)) == original
    assert source.hint_plan(retained) == source.hint_plan(legacy)
    assert collection.nwo.type == 'exclude' and all(not o.nwo.export_this for o in collection.all_objects)
    assert sum(o.type == 'MESH' for o in collection.all_objects) == 2
    packed = json.loads(bpy.data.texts[collection['h3_packed_data']].as_string())
    assert base64.b64decode(bpy.data.texts[packed[0]['text']].as_string()) == b'\x00\x01\xfe\xff'
    images = [n.image for o in collection.all_objects if o.type == 'MESH' for m in o.data.materials
              for n in m.node_tree.nodes if n.type == 'TEX_IMAGE']
    assert images and all(image.packed_file for image in images)
print('Chunked scenario Blender tests passed: hints, source preservation, repeated imports, rollback, save/reopen')

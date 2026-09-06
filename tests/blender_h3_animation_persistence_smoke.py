"""Persist staged actions without relying on temporary JMA files."""
from pathlib import Path
import runpy
import tempfile
import bpy
from mathutils import Matrix

# Reuse the numerical harness and its actual Foundry JMA parser.
h = runpy.run_path(str(Path(__file__).with_name('blender_h3_animation_smoke.py')))
B, settings, payload, rig, write_jma = (h[k] for k in ('B', 'settings', 'payload', 'rig', 'write_jma'))
near, matrix, converted = (h[k] for k in ('near', 'matrix', 'converted'))
settings.scale, settings.forward_direction = 'blender', 'x'
p = payload()
arm, mesh, source_action = rig(p['nodes'])
arm_name, source_action_name = arm.name, source_action.name
with tempfile.TemporaryDirectory() as folder:
    folder = Path(folder)
    frames = [[matrix(n) for n in p['nodes']] for _ in range(3)]
    motion = [[Matrix.Translation((float(i), 0, 0))] for i in range(3)]
    for i, frame in enumerate(frames):
        frame[0].translation.x += i
    decoded = p['animations'][0]['decoded']
    write_jma(folder / decoded['jma_file'], p['nodes'], frames)
    write_jma(folder / decoded['motion_file'], [{'name': 'movement', 'parent': -1}], motion)
    stage = B.AnimationStager(bpy.context, p, folder, arm)
    list(stage.build())
    new_name, collection_name = stage.armature.name, stage.collection.name
    staged_mesh = next(o for o in stage.collection.objects if o.type == 'MESH')
    assert staged_mesh.data == mesh.data
    assert staged_mesh.parent == stage.armature
    assert next(m for m in staged_mesh.modifiers if m.type == 'ARMATURE').object == stage.armature
    assert next(m for m in mesh.modifiers if m.type == 'ARMATURE').object == arm
    staged_mesh_name = staged_mesh.name
    bpy.context.scene.frame_set(3)
    bpy.context.view_layer.update()
    expected = {b.name: b.matrix.copy() for b in stage.armature.pose.bones}
    skin_expected = [v.co.copy() for v in staged_mesh.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices]
    for f in folder.iterdir():
        f.unlink()
    blend = folder / 'animations.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    settings.animations = bpy.context.scene.test_nwo.animations
    copied = bpy.data.objects[new_name]
    bpy.context.scene.frame_set(3)
    bpy.context.view_layer.update()
    for name, value in expected.items():
        near(copied.pose.bones[name].matrix, value)
    vertices = bpy.data.objects[staged_mesh_name].evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices
    for vertex, value in zip(vertices, skin_expected):
        assert (vertex.co - value).length < 1e-4
    assert bpy.data.objects[arm_name].animation_data.action.name == source_action_name
    collection = bpy.data.collections[collection_name]
    assert collection.nwo.type == 'exclude'
    assert bpy.data.texts[collection['h3_animation_manifest']].as_string()
    assert bpy.data.texts[collection['h3_animation_report']].as_string()
    row = next(r for r in settings.animations if r.action_tracks[0].object == copied)
    assert not row.export_this and row.animation_movement_data == 'xy'
    assert row.action_tracks[0].action == copied.animation_data.action
    assert copied.animation_data.action_slot is not None
    assert copied.nwo.node_order_source == ''

ops = h['importlib'].import_module(h['NAME'] + '.h3_import.animation_ops')
ops.register()
assert hasattr(bpy.ops.nwo, 'import_halo3_animations')
ops.unregister()
print('H3 animation persistence passed: saved actions, slots, skinning, source bindings, metadata, exclusions and operator registration')

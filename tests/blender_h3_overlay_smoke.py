"""Numerical time-overlay tests. Motion is synthetic, not an H3EK codec capture."""
import copy
import importlib
import json
from pathlib import Path
import sys
import tempfile
import bpy
from mathutils import Matrix, Quaternion, Vector
sys.path.insert(0, str(Path(__file__).parent))
import blender_h3_animation_smoke as base
from h3_overlay_fixture import payload

A = base.A
B = base.B
P = importlib.import_module(base.NAME + '.h3_import.animation_append')
settings = base.settings


def frames(manifest):
    reference = copy.deepcopy(manifest['animations'][0]['decoded']['overlay']['reference_pose'])
    last = copy.deepcopy(reference)
    last[0]['position'] = [v + d for v, d in zip(last[0]['position'], (1, 2, 3))]
    # Noncommuting X-reference/Z-delta detects reversed quaternion composition.
    last[0]['rotation'] = list(Quaternion(reference[0]['rotation']) @ Quaternion((0, 0, 1), 1.5707963267948966))
    last[0]['scale'] *= 1.25
    return [[Matrix.LocRotScale(Vector(t['position']), Quaternion(t['rotation']), Vector.Fill(3, t['scale']))
             for t in row] for row in (reference, reference, last)]


def verify(stage, action, expected, source_nodes):
    stage.armature.animation_data.action = action
    stage.armature.animation_data.action_slot = action.slots[0]
    for number, local in enumerate(expected, 1):
        bpy.context.scene.frame_set(number)
        bpy.context.view_layer.update()
        for node, matrix in zip(source_nodes, base.object_space(source_nodes, local)):
            base.near(stage.armature.pose.bones[stage.mapping[node['name']]].matrix, base.converted(matrix),
                      0.04 if settings.scale == 'max' else 0.004)
        for bone in stage.armature.data.bones:
            if bone.name.endswith('_atr_u'):
                base.near(stage.armature.pose.bones[bone.name].matrix,
                          stage.armature.pose.bones[bone.parent.name].matrix @ stage.rest_local[bone.name],
                          0.04 if settings.scale == 'max' else 0.004)
    assert action['h3_animation_reference_frame'] == 1
    assert action['h3_animation_first_sample_frame'] == 2
    assert action['h3_animation_preview'] == 'composed_on_fixed_reference'
    curves = base.utils.get_fcurves(action, action.slots[0])
    assert all(len(curve.keyframe_points) == 3 for curve in curves)
    assert action.frame_start == 1 and action.frame_end == 3


fixture = base.fixture
cases = [(False, False, 'blender', 'x', 'QUATERNION'),
         (False, True, 'blender', 'x', 'QUATERNION'),
         (True, False, 'blender', 'x', 'QUATERNION'),
         (True, True, 'blender', 'y', 'QUATERNION'),
         (True, False, 'max', 'x', 'XYZ'),
         (False, False, 'blender', 'y', 'AXIS_ANGLE')]
for native, staging, scale, forward, mode in cases:
    settings.scale, settings.forward_direction = scale, forward
    source_nodes = fixture['source_nodes']
    arm, mesh, keep = base.rig(fixture['target_nodes'] if native else source_nodes)
    for pb in arm.pose.bones:
        pb.rotation_mode = mode
    original_bones = tuple(arm.data.bones.keys())
    original_binding = (arm.data, mesh.data, mesh.parent, mesh.modifiers[0].object)
    before = base.snapshot()
    manifest = payload(source_nodes)
    A.validate_manifest(manifest)
    expected = frames(manifest)
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        base.write_jma(folder / 'clip_0005.jmo', source_nodes, expected)
        stage = (B.AnimationStager if staging else P.AnimationAppender)(bpy.context, manifest, folder, arm)
        list(stage.build())
        assert stage.animations[0].animation_type == 'overlay'
        assert stage.animations[0].animation_movement_data == 'none'
        assert not stage.animations[0].export_this
        assert stage.results[0]['status'].endswith('overlay_action')
        verify(stage, stage.first_action, expected, source_nodes)
        assert tuple(arm.data.bones.keys()) == original_bones
        assert (arm.data, mesh.data, mesh.parent, mesh.modifiers[0].object) == original_binding
        if not staging:
            assert stage.armature == arm
            assert base.snapshot()[:3] == before[:3]
            second = P.AnimationAppender(bpy.context, manifest, folder, arm)
            list(second.build())
            assert base.snapshot()[:3] == before[:3]
            verify(second, second.first_action, expected, source_nodes)
            second.rollback()
            assert arm.animation_data.action == stage.first_action
        else:
            assert arm.animation_data.action == keep
            assert stage.collection.nwo.type == 'exclude'
        stage.rollback()
        assert base.snapshot() == before
        assert arm.animation_data.action == keep
        assert all(pb.rotation_mode == mode for pb in arm.pose.bones)
    bpy.data.objects.remove(mesh, do_unlink=True)
    bpy.data.objects.remove(arm, do_unlink=True)

# A damaged leading reference is rejected after a prior clip, then fully rolled back.
settings.scale, settings.forward_direction = 'blender', 'x'
arm, mesh, keep = base.rig(fixture['source_nodes'])
manifest = payload(fixture['source_nodes'])
other = copy.deepcopy(manifest['animations'][0])
other.update(index=6, name='combat:fire_still')
other['decoded']['jma_file'] = 'bad.jmo'
manifest['animations'].insert(1, other)
A.validate_manifest(manifest)
before = base.snapshot()
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    expected = frames(manifest)
    base.write_jma(folder / 'clip_0005.jmo', manifest['nodes'], expected)
    broken = [[m.copy() for m in row] for row in expected]
    broken[0][0].translation.x += 1
    base.write_jma(folder / 'bad.jmo', manifest['nodes'], broken)
    stage = P.AnimationAppender(bpy.context, manifest, folder, arm)
    try:
        list(stage.build())
        raise AssertionError('Expected reference-frame rejection')
    except ValueError as exc:
        assert 'leading reference' in str(exc), str(exc)
    stage.rollback()
    assert base.snapshot() == before and arm.animation_data.action == keep

# Saved actions and references must outlive the extraction directory.
manifest = payload(fixture['source_nodes'])
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    expected = frames(manifest)
    base.write_jma(folder / 'clip_0005.jmo', manifest['nodes'], expected)
    stage = P.AnimationAppender(bpy.context, manifest, folder, arm)
    list(stage.build())
    verify(stage, stage.first_action, expected, manifest['nodes'])
    saved = {name: pb.matrix.copy() for name, pb in arm.pose.bones.items()}
    arm_name, mesh_name, action_name = arm.name, mesh.name, stage.first_action.name
    bindings = {(o.name, o.type) for o in bpy.context.scene.objects}
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / 'overlay.blend'))
    (folder / 'clip_0005.jmo').unlink()
    bpy.ops.wm.open_mainfile(filepath=str(folder / 'overlay.blend'))
    settings.animations = bpy.context.scene.test_nwo.animations
    arm, mesh, action = bpy.data.objects[arm_name], bpy.data.objects[mesh_name], bpy.data.actions[action_name]
    assert {(o.name, o.type) for o in bpy.context.scene.objects} == bindings
    assert mesh.parent == arm and mesh.modifiers[0].object == arm
    assert arm.animation_data.action == action and arm.animation_data.action_slot is not None
    assert action['h3_animation_reference_frame'] == 1
    source = json.loads(bpy.data.texts[arm['h3_animation_manifest']].as_string())
    assert source['animations'][0]['decoded']['overlay']['node_flags']['static_translation'][1]
    bpy.context.scene.frame_set(3)
    bpy.context.view_layer.update()
    for name, matrix in saved.items():
        base.near(arm.pose.bones[name].matrix, matrix)

ops = importlib.import_module(base.NAME + '.h3_import.animation_ops')
ops.register()
try:
    rna = bpy.ops.nwo.import_halo3_animations.get_rna_type()
    assert not rna.properties['include_overlays'].default
    assert not rna.properties['create_staging_copy'].default
finally:
    ops.unregister()
print('H3 time overlays passed: reference/body layout, independent composition oracle, native/H3 rigs, transforms, extra bones, rotation modes, append/staging, repeated import, rollback and persistence')

"""Discrete aim samples on synthetic H3/Reach rigs, including save/reopen."""
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
from h3_blend_screen_fixture import payload

A, B, settings = base.A, base.B, base.settings
P = importlib.import_module(base.NAME + '.h3_import.animation_append')


def frames(manifest):
    reference = manifest['animations'][0]['decoded']['overlay']['reference_pose']
    rows = [copy.deepcopy(reference)]
    for sample in range(9):
        row = copy.deepcopy(reference)
        row[0]['position'] = [v + d for v, d in zip(row[0]['position'], (sample * 0.1, -sample * 0.03, sample * 0.02))]
        row[0]['rotation'] = list(Quaternion(reference[0]['rotation']) @ Quaternion((0, 0, 1), (sample - 4) * 0.1))
        row[0]['scale'] *= 1 + sample * 0.01
        rows.append(row)
    return [[Matrix.LocRotScale(Vector(t['position']), Quaternion(t['rotation']), Vector.Fill(3, t['scale']))
             for t in row] for row in rows]


def verify(stage, expected, manifest):
    action = stage.first_action
    stage.armature.animation_data.action = action
    stage.armature.animation_data.action_slot = action.slots[0]
    for number, local in enumerate(expected, 1):
        # Inter-frame evaluation must hold the sample, not morph toward the next direction.
        for fraction in (0.0, 0.5):
            bpy.context.scene.frame_set(number, subframe=fraction)
            bpy.context.view_layer.update()
            for node, matrix in zip(manifest['nodes'], base.object_space(manifest['nodes'], local)):
                base.near(stage.armature.pose.bones[stage.mapping[node['name']]].matrix, base.converted(matrix),
                          0.04 if settings.scale == 'max' else 0.004)
            for bone in stage.armature.data.bones:
                if bone.name.endswith('_atr_u'):
                    base.near(stage.armature.pose.bones[bone.name].matrix,
                              stage.armature.pose.bones[bone.parent.name].matrix @ stage.rest_local[bone.name],
                              0.04 if settings.scale == 'max' else 0.004)
    assert action['h3_animation_reference_frame'] == 1 and action['h3_animation_first_sample_frame'] == 2
    assert action['h3_animation_sample_domain'] == 'blend_screen'
    assert action['h3_animation_preview'] == 'discrete_blend_screen_samples'
    assert json.loads(action['h3_animation_blend_screen']) == manifest['animations'][0]['decoded']['blend_screen']
    curves = base.utils.get_fcurves(action, action.slots[0])
    assert all(len(c.keyframe_points) == 10 for c in curves)
    assert all(k.interpolation == 'CONSTANT' for c in curves for k in c.keyframe_points)
    assert [(m.name, m.frame) for m in action.pose_markers] == [('H3 Reference', 1)] + [(f'H3 Sample {i:02d}', i+2) for i in range(9)]
    animation = stage.animations[0]
    assert animation.animation_type == 'overlay' and animation.animation_movement_data == 'none'
    assert not animation.export_this and not getattr(animation, 'pose_overlay', False)
    assert action.frame_start == 1 and action.frame_end == 10


fixture = base.fixture
for native, staging, scale, forward, mode in [
    (False,False,'blender','x','QUATERNION'), (True,False,'blender','x','QUATERNION'),
    (False,True,'blender','y','QUATERNION'), (True,True,'max','x','QUATERNION'),
    (True,False,'max','y','XYZ'), (False,False,'blender','y','AXIS_ANGLE')]:
    settings.scale, settings.forward_direction = scale, forward
    arm, mesh, keep = base.rig(fixture['target_nodes'] if native else fixture['source_nodes'])
    for pb in arm.pose.bones: pb.rotation_mode = mode
    original = (arm.data, mesh.data, mesh.parent, mesh.modifiers[0].object, tuple(arm.data.bones.keys()))
    before = base.snapshot()
    manifest = payload(fixture['source_nodes'])
    A.validate_manifest(manifest)
    expected = frames(manifest)
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        base.write_jma(folder / 'clip_0001.jmo', manifest['nodes'], expected)
        stage = (B.AnimationStager if staging else P.AnimationAppender)(bpy.context, manifest, folder, arm)
        list(stage.build())
        verify(stage, expected, manifest)
        assert (arm.data, mesh.data, mesh.parent, mesh.modifiers[0].object, tuple(arm.data.bones.keys())) == original
        if not staging:
            assert base.snapshot()[:3] == before[:3]
            second = P.AnimationAppender(bpy.context, manifest, folder, arm)
            list(second.build())
            verify(second, expected, manifest)
            assert base.snapshot()[:3] == before[:3]
            second.rollback()
            assert arm.animation_data.action == stage.first_action
        else:
            assert arm.animation_data.action == keep and stage.collection.nwo.type == 'exclude'
        stage.rollback()
        assert base.snapshot() == before and arm.animation_data.action == keep
        assert all(pb.rotation_mode == mode for pb in arm.pose.bones)
    bpy.data.objects.remove(mesh, do_unlink=True)
    bpy.data.objects.remove(arm, do_unlink=True)

# Preserve the successful first action only if the complete import succeeds.
settings.scale, settings.forward_direction = 'blender', 'x'
arm, mesh, keep = base.rig(fixture['source_nodes'])
manifest = payload(fixture['source_nodes'])
other = copy.deepcopy(manifest['animations'][0])
other.update(index=0, name='combat:aim_move_up')
other['decoded']['jma_file'] = 'bad.jmo'
manifest['animations'].insert(1, other)
A.validate_manifest(manifest)
before = base.snapshot()
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    expected = frames(manifest)
    base.write_jma(folder / 'clip_0001.jmo', manifest['nodes'], expected)
    broken = [[m.copy() for m in row] for row in expected]
    broken[0][0].translation.z += 1
    base.write_jma(folder / 'bad.jmo', manifest['nodes'], broken)
    stage = P.AnimationAppender(bpy.context, manifest, folder, arm)
    try:
        list(stage.build())
        raise AssertionError('Expected bad-reference failure')
    except ValueError as exc:
        assert 'leading reference' in str(exc), str(exc)
    stage.rollback()
    assert base.snapshot() == before and arm.animation_data.action == keep

# The source-order pose bank must survive deletion of its extraction files.
manifest = payload(fixture['source_nodes'])
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    expected = frames(manifest)
    base.write_jma(folder / 'clip_0001.jmo', manifest['nodes'], expected)
    stage = P.AnimationAppender(bpy.context, manifest, folder, arm)
    list(stage.build())
    verify(stage, expected, manifest)
    bpy.context.scene.frame_set(7, subframe=0.5)
    saved = {name: pb.matrix.copy() for name, pb in arm.pose.bones.items()}
    arm_name, mesh_name, action_name = arm.name, mesh.name, stage.first_action.name
    bindings = {(o.name, o.type) for o in bpy.context.scene.objects}
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / 'aim_samples.blend'))
    (folder / 'clip_0001.jmo').unlink()
    bpy.ops.wm.open_mainfile(filepath=str(folder / 'aim_samples.blend'))
    settings.animations = bpy.context.scene.test_nwo.animations
    arm, mesh, action = bpy.data.objects[arm_name], bpy.data.objects[mesh_name], bpy.data.actions[action_name]
    assert {(o.name, o.type) for o in bpy.context.scene.objects} == bindings
    assert mesh.parent == arm and mesh.modifiers[0].object == arm
    assert arm.animation_data.action == action and arm.animation_data.action_slot is not None
    assert len(action.pose_markers) == 10
    assert json.loads(action['h3_animation_blend_screen'])['sample_count'] == 9
    source = json.loads(bpy.data.texts[arm['h3_animation_manifest']].as_string())
    assert source['animations'][0]['decoded']['blend_screen']['counts']['right'] == 1
    bpy.context.scene.frame_set(7, subframe=0.5)
    bpy.context.view_layer.update()
    for name, matrix in saved.items(): base.near(arm.pose.bones[name].matrix, matrix)

ops = importlib.import_module(base.NAME + '.h3_import.animation_ops')
ops.register()
try:
    rna = bpy.ops.nwo.import_halo3_animations.get_rna_type()
    assert not rna.properties['include_blend_screens'].default
    assert not rna.properties['include_overlays'].default
    assert not rna.properties['create_staging_copy'].default
finally:
    ops.unregister()
print('H3 blend-screen checks passed: all nine samples, reference, stepped evaluation, H3/Reach rigs, rotation modes, no duplicate geometry, rollback, markers, metadata and reopen')

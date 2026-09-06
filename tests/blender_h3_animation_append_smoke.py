"""Existing-armature import checks with synthetic motion and Scarab rest metadata."""
import copy
import fnmatch
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import bpy
from mathutils import Matrix

sys.path.insert(0, str(Path(__file__).parent))
import blender_h3_animation_smoke as base

Appender = importlib.import_module(base.NAME + '.h3_import.animation_append').AnimationAppender
ops = importlib.import_module(base.NAME + '.h3_import.animation_ops')


def geometry_snapshot():
    return tuple(len(s) for s in (bpy.data.objects, bpy.data.meshes,
                                 bpy.data.armatures, bpy.data.collections))


def scene_bindings():
    return sorted((ob.name, ob.type, ob.data.name if ob.data else '',
                   ob.parent.name if ob.parent else '',
                   tuple((m.name, m.object.name if m.object else '')
                         for m in ob.modifiers if m.type == 'ARMATURE'))
                  for ob in bpy.context.scene.objects)


def make_clip(folder, nodes, kind='JMT', name='combat:move_front'):
    manifest = base.payload()
    manifest['nodes'] = copy.deepcopy(nodes)
    frames, motions = [], []
    rest = [base.matrix(n) for n in nodes]
    for f in range(3):
        motion = Matrix.Identity(4)
        if kind != 'JMM':
            motion = Matrix.Translation((f, f * 0.25, 0)) @ Matrix.Rotation(f * 0.25 if kind == 'JMT' else 0, 4, 'Z')
        frame = [m.copy() for m in rest]
        frame[1] = frame[1] @ Matrix.Rotation(f * 0.1, 4, 'Y')
        loc, rot, scale = frame[0].decompose()
        frame[0] = Matrix.LocRotScale(loc + motion.translation, motion.to_quaternion() @ rot, scale)
        frames.append(frame)
        motions.append([motion])
    decoded = {'kind': kind, 'jma_file': 'clip.' + kind.lower(),
               'motion_file': None if kind == 'JMM' else 'motion.' + kind.lower(),
               'decoded_frame_count': 2, 'file_frame_count': 3, 'fps': 30,
               'frame_layout': 'codec_frames_then_held_terminal'}
    clip = {'name': name, 'index': 0, 'status': 'decoded', 'source_node_count': len(nodes),
            'source_frame_count': 2, 'animation_type': 'base', 'world_relative': False,
            'frame_info_type': {'JMM': 'none', 'JMA': 'dx,dy', 'JMT': 'dx,dy,dyaw'}[kind],
            'decoded': decoded}
    manifest['animations'] = [clip]
    base.write_jma(folder / decoded['jma_file'], nodes, frames)
    if decoded['motion_file']:
        base.write_jma(folder / decoded['motion_file'], [{'name': 'movement', 'parent': -1}], motions)
    base.A.validate_manifest(manifest)
    return manifest, frames


cases = [(False, 'blender', 'x', 'QUATERNION'),
         (False, 'blender', 'y', 'XYZ'),
         (True, 'blender', 'x', 'QUATERNION'),
         (True, 'blender', 'y', 'AXIS_ANGLE'),
         (True, 'max', 'x', 'ZYX')]
for native, scale, forward, mode in cases:
    base.settings.scale, base.settings.forward_direction = scale, forward
    nodes = base.fixture['source_nodes']
    arm, mesh, old = base.rig(base.fixture['target_nodes'] if native else nodes)
    old.use_fake_user = False
    old_slot = arm.animation_data.action_slot
    for pb in arm.pose.bones:
        pb.rotation_mode = mode
    arm.nwo.node_order_source = 'existing_order.render_model'
    mesh.nwo.export_this = False
    original_bones = [(b.name, b.parent.name if b.parent else None, b.matrix_local.copy()) for b in arm.data.bones]
    original_pose = {pb.name: pb.matrix_basis.copy() for pb in arm.pose.bones}
    counts = geometry_snapshot()
    before = base.snapshot()
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        manifest, frames = make_clip(folder, nodes)
        first = Appender(bpy.context, manifest, folder, arm)
        list(first.build())
        assert first.armature == arm and first.collection is None
        assert geometry_snapshot() == counts
        assert len(arm.data.bones) == (47 if native else 33)
        assert first.motion_target == ('pedestal' if native else 'source_root')
        assert old in bpy.data.actions.values() and old.use_fake_user
        assert old.slots[0] == old_slot
        assert arm.nwo.node_order_source == 'existing_order.render_model'
        assert not mesh.nwo.export_this
        assert all(not row.export_this for row in first.animations)
        assert mesh.parent == arm and mesh.modifiers[0].object == arm
        for name, parent, rest in original_bones:
            bone = arm.data.bones[name]
            assert (bone.parent.name if bone.parent else None) == parent
            base.near(bone.matrix_local, rest)
            assert arm.pose.bones[name].rotation_mode == mode
        for frame_index, frame in enumerate(frames, 1):
            bpy.context.scene.frame_set(frame_index)
            for node, world in zip(nodes, base.object_space(nodes, frame)):
                base.near(arm.pose.bones[first.mapping[node['name']]].matrix, base.converted(world),
                          0.03 if scale == 'max' else 0.003)
        action = arm.animation_data.action
        report = arm['h3_animation_report']
        second_manifest, _ = make_clip(folder, nodes, 'JMM', 'combat:idle')
        second = Appender(bpy.context, second_manifest, folder, arm)
        list(second.build())
        assert geometry_snapshot() == counts
        assert action in bpy.data.actions.values() and action.use_fake_user
        assert second.first_action != action
        assert second.first_action.slots[0].target_id_type == 'OBJECT'
        second.rollback()
        assert arm.animation_data.action == action and arm['h3_animation_report'] == report
        first.rollback()
        first.rollback()
        assert arm.animation_data.action == old and arm.animation_data.action_slot == old_slot
        assert not old.use_fake_user
        assert base.snapshot() == before
        for name, pose in original_pose.items():
            base.near(arm.pose.bones[name].matrix_basis, pose)
    bpy.data.objects.remove(mesh, do_unlink=True)
    bpy.data.objects.remove(arm, do_unlink=True)

base.settings.scale, base.settings.forward_direction = 'blender', 'x'
arm, mesh, old = base.rig(base.fixture['source_nodes'])
old.use_fake_user = False
arm['h3_animation_report'] = 'previous report'
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    manifest, frames = make_clip(folder, base.fixture['source_nodes'])
    # A failure after replacing the active action must restore the previous slot and users.
    invalid = copy.deepcopy(manifest)
    missing = copy.deepcopy(invalid['animations'][0])
    missing.update(index=1, name='combat:missing')
    missing['decoded']['jma_file'] = 'missing.jmt'
    invalid['animations'].append(missing)
    before = base.snapshot()
    stage = Appender(bpy.context, invalid, folder, arm)
    try:
        list(stage.build())
        raise AssertionError('Expected missing payload failure')
    except FileNotFoundError:
        stage.rollback()
    assert base.snapshot() == before
    assert arm.animation_data.action == old and not old.use_fake_user
    assert arm['h3_animation_report'] == 'previous report'
    # Cancellation before or after creating a clip must not leave partial data.
    for steps_to_take in (1, 2):
        stage = Appender(bpy.context, manifest, folder, arm)
        steps = iter(stage.build())
        for _ in range(steps_to_take):
            next(steps)
        steps.close()
        stage.rollback()
        assert base.snapshot() == before and arm.animation_data.action == old
    constraint = arm.pose.bones[0].constraints.new('COPY_ROTATION')
    constraint.target = arm
    stage = Appender(bpy.context, manifest, folder, arm)
    try:
        list(stage.build())
        raise AssertionError('Expected constrained target rejection')
    except ValueError as exc:
        assert 'Create Staging Copy' in str(exc)
    stage.rollback()
    assert not constraint.mute and base.snapshot() == before
    arm.pose.bones[0].constraints.remove(constraint)
    arm.animation_data_clear()
    before_empty = base.snapshot()
    empty = Appender(bpy.context, manifest, folder, arm)
    list(empty.build())
    assert arm.animation_data is not None
    empty.rollback()
    assert arm.animation_data is None and base.snapshot() == before_empty
    arm.animation_data_create()
    arm.animation_data.action = old
    arm.animation_data.action_slot = old.slots[0]
    # Saved playback must survive removal of all extraction files.
    stage = Appender(bpy.context, manifest, folder, arm)
    list(stage.build())
    arm_name, mesh_name, old_name = arm.name, mesh.name, old.name
    # Unused datablocks from earlier fixtures are not saved. Check live scene bindings.
    saved_bindings = scene_bindings()
    bpy.context.scene.frame_set(3)
    expected = arm.pose.bones[stage.mapping['hull']].matrix.copy()
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / 'appended.blend'))
    for f in folder.iterdir():
        if f.suffix != '.blend':
            f.unlink()
    bpy.ops.wm.open_mainfile(filepath=str(folder / 'appended.blend'))
    base.settings.animations = bpy.context.scene.test_nwo.animations
    arm, mesh = bpy.data.objects[arm_name], bpy.data.objects[mesh_name]
    assert scene_bindings() == saved_bindings
    assert mesh.parent == arm and mesh.modifiers[0].object == arm
    assert bpy.data.actions.get(old_name) is not None
    assert arm.animation_data.action_slot is not None
    assert arm.get('h3_animation_manifest') in bpy.data.texts
    assert arm.get('h3_animation_report') in bpy.data.texts
    bpy.context.scene.frame_set(3)
    base.near(arm.pose.bones['hull'].matrix, expected)

ops.register()
try:
    bpy.context.view_layer.objects.active = None
    assert ops.NWO_OT_ImportH3Animations.poll(bpy.context)
    rna = bpy.ops.nwo.import_halo3_animations.get_rna_type()
    assert not rna.properties['create_staging_copy'].default
    assert 'target_armature' in rna.properties
    patterns = rna.properties['filter_glob'].default.split(';')
    assert all(len(pattern) < 16 for pattern in patterns), patterns
    for name in ('scarab.model_animation_graph', 'scarab.model', 'scarab.giant', 'test.h3anim.json'):
        assert any(fnmatch.fnmatchcase(name, pattern[:15]) for pattern in patterns), name
    base.settings.export_in_progress = True
    assert not ops.NWO_OT_ImportH3Animations.poll(bpy.context)
    base.settings.export_in_progress = False
finally:
    ops.unregister()
print('H3 append tests passed: no duplicate geometry, source-root and pedestal motion, rotation modes, repeated imports, prior actions, rollback, cancellation, constrained-rig rejection, save/reopen, target UI and long-extension filter')

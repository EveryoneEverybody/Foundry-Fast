"""Add H3 actions to an existing rig without duplicating geometry."""
import json
import bpy
from mathutils import Quaternion
from .animation_builder import AnimationStager, _ordered, source_rest_world
from .animations import CONTROL_PREFIXES, node_mapping


class AnimationAppender(AnimationStager):
    def __init__(self, context, manifest, folder, selected_armature):
        super().__init__(context, manifest, folder, selected_armature)
        self._saved = None
        self._metadata = {}
        self._rolled_back = False

    def stage_rig(self):
        arm = self.original
        if arm.library or arm.data.library:
            raise ValueError('Select a local editable armature')
        if arm.mode != 'OBJECT':
            raise ValueError('Switch the target armature to Object Mode')
        constraints = list(arm.constraints)
        for pb in arm.pose.bones:
            constraints.extend(pb.constraints)
        if any(not c.mute and c.influence != 0 for c in constraints):
            raise ValueError('Target has active constraints. Enable Create Staging Copy to isolate animation playback')
        data = arm.animation_data
        if data:
            if data.action_blend_type != 'REPLACE' or data.action_influence != 1.0:
                raise ValueError('Target uses action blending. Enable Create Staging Copy to isolate animation playback')
            if data.use_nla and any(not t.mute and len(t.strips) for t in data.nla_tracks):
                raise ValueError('Target has active NLA strips. Enable Create Staging Copy to isolate animation playback')
            if any(not c.mute and c.data_path.startswith('pose.bones[') for c in data.drivers):
                raise ValueError('Target has pose drivers. Enable Create Staging Copy to isolate animation playback')
        parents = {b.name: b.parent.name if b.parent else None for b in arm.data.bones}
        self.mapping, pedestal = node_mapping(self.manifest['nodes'], parents)
        rest = source_rest_world(self.manifest, self.factor * 100, self.rotation)
        errors = []
        for name, target in self.mapping.items():
            error = max(abs(rest[name][r][c] - arm.data.bones[target].matrix_local[r][c])
                        for r in range(4) for c in range(4))
            if error > 0.002:
                errors.append(f'{name} -> {target}: {error:.6g}')
        if errors:
            raise ValueError('Selected rig bind pose differs from H3 source: ' + '; '.join(errors[:8]))
        self.bones = _ordered([b for b in arm.data.bones if not b.name.startswith(CONTROL_PREFIXES)])
        names = {b.name for b in self.bones}
        if any(b.parent and b.parent.name not in names for b in self.bones):
            raise ValueError('Target deform hierarchy contains control parents; use a source armature')
        # Existing H3 rigs keep folded movement on their source root. No bone insertion.
        self.pedestal = pedestal or self.mapping[self.manifest['nodes'][0]['name']]
        self.motion_target = 'pedestal' if pedestal else 'source_root'
        self.rest_local = {b.name: (b.parent.matrix_local.inverted() @ b.matrix_local
                                   if b.parent else b.matrix_local.copy()) for b in self.bones}
        old_action = data.action if data else None
        self._saved = {
            'has_data': data is not None,
            'action': old_action,
            'slot': data.action_slot if data else None,
            'fake_user': old_action.use_fake_user if old_action else None,
            'pose': {pb.name: pb.matrix_basis.copy() for pb in arm.pose.bones},
        }
        self._metadata = {key: (key in arm, arm.get(key))
                          for key in ('h3_animation_manifest', 'h3_animation_report')}
        self.armature = arm
        source = self.remember(bpy.data.texts, bpy.data.texts.new('H3 animation source - ' + arm.name))
        source.write(json.dumps(self.manifest, indent=2))
        arm['h3_animation_manifest'] = source.name

    def build_action(self, clip):
        # Preserve the previous action even if its active slot was its only user.
        old_action = self._saved['action']
        if old_action:
            old_action.use_fake_user = True
        action = super().build_action(clip)
        action['h3_animation_motion_target'] = self.motion_target
        self._match_rotation_modes(action)
        return action

    def _match_rotation_modes(self, action):
        from .. import utils
        curves = utils.get_fcurves(action, action.slots[0])
        for bone in self.bones:
            pb = self.armature.pose.bones[bone.name]
            mode = pb.rotation_mode
            if mode == 'QUATERNION':
                continue
            path = pb.path_from_id()
            source = [curves.find(path + '.rotation_quaternion', index=i) for i in range(4)]
            samples = []
            previous = None
            for index in range(len(source[0].keyframe_points)):
                quat = Quaternion([curve.keyframe_points[index].co.y for curve in source])
                quat.normalize()
                if mode == 'AXIS_ANGLE':
                    axis, angle = quat.to_axis_angle()
                    values = (angle, *axis)
                else:
                    values = quat.to_euler(mode, previous) if previous is not None else quat.to_euler(mode)
                    previous = values.copy()
                samples.append(tuple(values))
            prop = 'rotation_axis_angle' if mode == 'AXIS_ANGLE' else 'rotation_euler'
            for component in range(len(samples[0])):
                curve = curves.new(data_path=f'{path}.{prop}', index=component)
                curve.keyframe_points.add(len(samples))
                curve.keyframe_points.foreach_set('co', [v for frame, values in enumerate(samples, 1)
                                                        for v in (frame, values[component])])
                for key in curve.keyframe_points:
                    key.interpolation = 'LINEAR'
                curve.update()
            for curve in source:
                curves.remove(curve)

    def build(self):
        if not any(c['status'] == 'decoded' for c in self.manifest['animations']):
            raise ValueError('No supported clips decoded. Check the animation helper log and manifest')
        self.stage_rig()
        yield 'Using existing armature'
        for clip in self.manifest['animations']:
            if clip['status'] != 'decoded':
                self.results.append({'name': clip['name'], 'status': clip['status'], 'message': clip.get('message', '')})
                continue
            self.build_action(clip)
            self.results.append({'name': clip['name'], 'status': 'appended_' + clip['animation_type'] + '_action',
                                 'frames': clip['decoded']['file_frame_count']})
            yield clip['name']
        arm = self.armature
        arm.animation_data.action = self.first_action
        arm.animation_data.action_slot = self.first_action.slots[0]
        self.context.scene.frame_start = 1
        self.context.scene.frame_end = int(self.first_action.frame_end)
        self.context.scene.render.fps = 30
        self.context.scene.render.fps_base = 1.0
        self.context.scene.frame_set(1)
        report = self.remember(bpy.data.texts, bpy.data.texts.new('H3 animation staging report'))
        report.write(json.dumps({'format': 'foundry.h3-animation-staging', 'version': 1,
            'target_mode': 'existing_armature', 'armature': arm.name,
            'results': self.results, 'node_map': self.mapping,
            'movement_node': self.pedestal, 'motion_target': self.motion_target,
            'notes': ['No objects, mesh data, or bones duplicated or changed.',
                      'Existing actions retained; the first new action is active.',
                      'New animation entries excluded from export. Existing exclusions unchanged.',
                      'Source-root movement stays folded on H3 rigs without a pedestal.',
                      'Events retained, not converted. No Reach tags written.',
                      'JMO frame 1 is the composition reference; frames 2 onward are codec samples.',
                      'Time overlays are standalone composed previews, not NLA layers.']}, indent=2))
        arm['h3_animation_report'] = report.name
        self.context.view_layer.update()

    def rollback(self):
        if self._rolled_back:
            return
        self._rolled_back = True
        arm = self.original
        if self._saved is not None:
            saved = self._saved
            if saved['has_data']:
                arm.animation_data_create()
                arm.animation_data.action = saved['action']
                if saved['action'] is not None:
                    arm.animation_data.action_slot = saved['slot']
            else:
                arm.animation_data_clear()
            if saved['action'] is not None:
                saved['action'].use_fake_user = saved['fake_user']
            for name, matrix in saved['pose'].items():
                if name in arm.pose.bones:
                    arm.pose.bones[name].matrix_basis = matrix
            for key, (present, value) in self._metadata.items():
                if present:
                    arm[key] = value
                elif key in arm:
                    del arm[key]
        super().rollback()
        self.context.view_layer.update()

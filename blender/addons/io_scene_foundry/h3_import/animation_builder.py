"""Stage decoded clips on a copy of the selected armature."""
import json
import math
from pathlib import Path
import bpy
from mathutils import Matrix, Quaternion, Vector
from .. import utils
from ..legacy.jma import JMA
from ..managed_blam import import_transform
from .animations import KINDS, is_blend_screen, CONTROL_PREFIXES, canonical_node, node_mapping, safe_file, validate_jma_header


def find_armature(context):
    ob = context.object
    seen = set()
    while ob is not None and ob.as_pointer() not in seen:
        seen.add(ob.as_pointer())
        if ob.type == 'ARMATURE':
            return ob
        if ob.type == 'MESH':
            armature = ob.find_armature()
            if armature is not None:
                return armature
        # Bone-parented reference meshes may have no armature modifier.
        ob = ob.parent
    return None


def _ordered(bones):
    def depth(b):
        d = 0
        while b.parent is not None:
            d += 1
            b = b.parent
        return d
    return sorted(bones, key=depth)


def _rest_matrix(rest, factor):
    return Matrix.LocRotScale(Vector(rest['position']) * factor,
                              Quaternion(rest['rotation']), Vector.Fill(3, rest['scale']))


def bind_pose_error(source, target, factor):
    """Compare basis elements directly and translation in Blender-scale units."""
    basis_error = max(abs(source[r][c] - target[r][c]) for r in range(3) for c in range(3))
    position_error = max(abs(source[r][3] - target[r][3]) for r in range(3)) * 0.03048 / factor
    return max(basis_error, position_error)


def source_rest_world(manifest, factor, rotation):
    world = {}
    for node in manifest['nodes']:
        matrix = _rest_matrix(node['rest'], factor)
        world[node['name']] = (rotation @ matrix if node['parent'] == -1 else
                              world[manifest['nodes'][node['parent']]['name']] @ matrix)
    return world


def _read_jma(path, frames, nodes):
    validate_jma_header(path, frames, nodes)
    result = JMA()
    result.from_file(path)
    if len(result.nodes) != nodes or len(result.transforms) != frames:
        raise ValueError('JMA payload dimensions disagree with header')
    for frame in result.transforms:
        for matrix in frame.values():
            if any(not math.isfinite(x) for row in matrix for x in row):
                raise ValueError('JMA contains non-finite transforms')
    return result


class AnimationStager:
    def __init__(self, context, manifest, folder, selected_armature):
        self.context, self.manifest, self.folder = context, manifest, Path(folder)
        self.original = selected_armature
        self.settings = utils.get_scene_props()
        self.factor = import_transform.scale_factor(self.settings)
        self.rotation = import_transform.rotation_matrix(self.settings)
        self.created, self.animations = [], []
        self.results = []
        self.armature = None
        self.collection = None
        self.first_action = None

    def remember(self, store, obj):
        self.created.append((store, obj))
        return obj

    def stage_rig(self):
        source = self.original
        if source.library or source.data.library:
            raise ValueError('Select a local editable armature')
        root = self.remember(bpy.data.collections, bpy.data.collections.new('H3 animation - ' + source.name))
        self.context.scene.collection.children.link(root)
        root.nwo.type = 'exclude'
        self.collection = root
        arm = self.remember(bpy.data.objects, source.copy())
        arm.data = self.remember(bpy.data.armatures, source.data.copy())
        arm.name = source.name + ' H3 animations'
        arm.animation_data_clear()
        root.objects.link(arm)
        self.armature = arm
        for pb in arm.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)
            pb.rotation_mode = 'QUATERNION'
            for con in pb.constraints:
                con.mute = True
        for con in arm.constraints:
            con.mute = True
        # Copy only objects actually driven by this armature. Mesh data stays shared.
        for ob in list(self.context.scene.objects):
            if ob in (source, arm):
                continue
            driven = ob.parent == source or any(m.type == 'ARMATURE' and m.object == source for m in ob.modifiers)
            if not driven:
                continue
            copy = self.remember(bpy.data.objects, ob.copy())
            copy.animation_data_clear()
            root.objects.link(copy)
            if ob.parent == source:
                copy.parent = arm
            for mod in copy.modifiers:
                if mod.type == 'ARMATURE' and mod.object == source:
                    mod.object = arm
            # Preserve export exclusions from any source collection.
            if any(getattr(c.nwo, 'type', '') == 'exclude' for c in ob.users_collection):
                copy.nwo.export_this = False
        for ob in self.context.selected_objects:
            ob.select_set(False)
        arm.select_set(True)
        self.context.view_layer.objects.active = arm
        parents = {b.name: b.parent.name if b.parent else None for b in arm.data.bones}
        mapping, pedestal = node_mapping(self.manifest['nodes'], parents)
        if pedestal is None:
            # Keep hull motion distinct from the exported movement node.
            bpy.ops.object.mode_set(mode='EDIT')
            try:
                bone = arm.data.edit_bones.new('b_pedestal')
                bone.head, bone.tail = (0, 0, 0), (0, max(self.factor * 5, 0.01), 0)
                bone.matrix = self.rotation
                bone.use_deform = True
                child = arm.data.edit_bones[mapping[self.manifest['nodes'][0]['name']]]
                saved = child.matrix.copy()
                child.parent = bone
                child.matrix = saved
                pedestal = bone.name
            finally:
                bpy.ops.object.mode_set(mode='OBJECT')
            # A changed node list must not claim the old node-order tag.
            arm.nwo.node_order_source = ''
        self.context.view_layer.update()
        self.mapping, self.pedestal = mapping, pedestal
        rest = source_rest_world(self.manifest, self.factor * 100, self.rotation)
        errors = []
        for name, target in mapping.items():
            error = bind_pose_error(rest[name], arm.data.bones[target].matrix_local, self.factor)
            if error > 0.002:
                errors.append(f'{name} -> {target}: {error:.6g}')
        if errors:
            raise ValueError('Selected rig bind pose differs from H3 source: ' + '; '.join(errors[:8]))
        self.bones = _ordered([b for b in arm.data.bones if not b.name.startswith(CONTROL_PREFIXES)])
        self.rest_local = {b.name: (b.parent.matrix_local.inverted() @ b.matrix_local if b.parent else b.matrix_local.copy()) for b in self.bones}
        root['h3_animation_node_map'] = json.dumps(mapping)
        root['h3_animation_pedestal'] = pedestal
        root['h3_animation_source_graph'] = self.manifest['source_graph']
        report = self.remember(bpy.data.texts, bpy.data.texts.new('H3 animation source - ' + source.name))
        report.write(json.dumps(self.manifest, indent=2))
        root['h3_animation_manifest'] = report.name

    def frame_worlds(self, clip):
        d = clip['decoded']
        jma = _read_jma(safe_file(self.folder, d['jma_file']), d['file_frame_count'], len(self.manifest['nodes']))
        node_by_name = {n.name: n for n in jma.nodes}
        if set(node_by_name) != set(self.mapping):
            raise ValueError('JMA node names differ from manifest')
        for n in self.manifest['nodes']:
            parent = node_by_name[n['name']].parent
            expected = self.manifest['nodes'][n['parent']]['name'] if n['parent'] != -1 else None
            if (parent.name if parent else None) != expected:
                raise ValueError('JMA hierarchy differs from manifest')
        if d['kind'] == 'JMO':
            reference = d['overlay']['reference_pose']
            for node, transform in zip(self.manifest['nodes'], reference):
                expected = _rest_matrix(transform, 100)
                actual = jma.transforms[0][node_by_name[node['name']]]
                if any(abs(actual[row][col] - expected[row][col]) > 1e-4 * max(1, abs(expected[row][col]))
                       for row in range(4) for col in range(4)):
                    raise ValueError('JMO leading reference disagrees with manifest for ' + node['name'])
        motion = None
        if d.get('motion_file'):
            motion = _read_jma(safe_file(self.folder, d['motion_file']), d['file_frame_count'], 1)
        for i, frame in enumerate(jma.transforms):
            source_world = {}
            for n in self.manifest['nodes']:
                matrix = frame[node_by_name[n['name']]].copy()
                matrix.translation *= self.factor
                source_world[n['name']] = (self.rotation @ matrix if n['parent'] == -1 else
                    source_world[self.manifest['nodes'][n['parent']]['name']] @ matrix)
            desired = {self.mapping[name]: matrix for name, matrix in source_world.items()}
            if self.pedestal not in desired:
                matrix = Matrix.Identity(4) if motion is None else motion.transforms[i][motion.nodes[0]].copy()
                matrix.translation *= self.factor
                desired[self.pedestal] = self.rotation @ matrix
            for b in self.bones:
                if b.name not in desired:
                    desired[b.name] = (desired[b.parent.name] @ self.rest_local[b.name] if b.parent else self.rest_local[b.name].copy())
            yield desired

    def build_action(self, clip):
        arm = self.armature
        channels = {b.name: [[] for _ in range(10)] for b in self.bones}
        previous = {}
        for frame in self.frame_worlds(clip):
            for b in self.bones:
                local = frame[b.parent.name].inverted() @ frame[b.name] if b.parent else frame[b.name]
                basis = self.rest_local[b.name].inverted() @ local
                loc, rot, scale = basis.decompose()
                if b.name in previous and rot.dot(previous[b.name]) < 0:
                    rot.negate()
                previous[b.name] = rot.copy()
                for dest, value in zip(channels[b.name], (*loc, *rot, *scale)):
                    dest.append(value)
        action = self.remember(bpy.data.actions, bpy.data.actions.new(clip['name']))
        action.use_fake_user = True
        action['h3_animation_source_graph'] = self.manifest['source_graph']
        action['h3_animation_source_name'] = clip['name']
        action['h3_animation_source_index'] = clip['index']
        action['h3_animation_source_record'] = json.dumps(clip)
        action['h3_animation_pedestal'] = self.pedestal
        if clip['decoded']['kind'] == 'JMO':
            action['h3_animation_reference_frame'] = 1
            action['h3_animation_first_sample_frame'] = 2
            action['h3_animation_preview'] = clip['decoded']['overlay']['preview']
        interpolation = 'CONSTANT' if is_blend_screen(clip) else 'LINEAR'
        if is_blend_screen(clip):
            action['h3_animation_sample_domain'] = 'blend_screen'
            action['h3_animation_interpolation'] = interpolation
            action['h3_animation_blend_screen'] = json.dumps(clip['decoded']['blend_screen'])
            action.pose_markers.new('H3 Reference').frame = 1
            for sample in range(clip['decoded']['decoded_frame_count']):
                action.pose_markers.new(f'H3 Sample {sample:02d}').frame = sample + 2
        arm.animation_data_create()
        slot = action.slots.new('OBJECT', arm.name)
        arm.animation_data.action = action
        arm.animation_data.action_slot = slot
        curves = utils.get_fcurves(action, slot)
        for bone, values in channels.items():
            path = arm.pose.bones[bone].path_from_id()
            for index, samples in enumerate(values):
                prop, component = (('location', index) if index < 3 else
                    ('rotation_quaternion', index - 3) if index < 7 else ('scale', index - 7))
                curve = curves.new(data_path=f'{path}.{prop}', index=component)
                curve.keyframe_points.add(len(samples))
                curve.keyframe_points.foreach_set('co', [x for f, v in enumerate(samples, 1) for x in (f, v)])
                for key in curve.keyframe_points:
                    key.interpolation = interpolation
                curve.update()
        animation = self.settings.animations.add()
        self.animations.append(animation)
        animation.name = clip['name'].replace(':', ' ')
        animation.frame_start = 1
        animation.frame_end = clip['decoded']['file_frame_count']
        animation.animation_type = clip['animation_type']
        animation.animation_movement_data = KINDS[clip['decoded']['kind']]
        animation.export_this = False
        track = animation.action_tracks.add()
        track.object, track.action = arm, action
        action.use_frame_range = True
        action.frame_start, action.frame_end = 1, animation.frame_end
        if self.first_action is None:
            self.first_action = action
        return action

    def build(self):
        if not any(c['status'] == 'decoded' for c in self.manifest['animations']):
            raise ValueError('No supported clips decoded. Check the animation helper log and manifest')
        self.stage_rig()
        yield 'Staging armature'
        for clip in self.manifest['animations']:
            if clip['status'] != 'decoded':
                self.results.append({'name': clip['name'], 'status': clip['status'], 'message': clip.get('message', '')})
                continue
            self.build_action(clip)
            self.results.append({'name': clip['name'], 'status': 'staged_' + clip['animation_type'] + '_action',
                                 'frames': clip['decoded']['file_frame_count']})
            yield clip['name']
        arm = self.armature
        arm.animation_data.action = self.first_action
        arm.animation_data.action_slot = self.first_action.slots[0]
        self.context.scene.frame_set(1)
        self.context.scene.frame_start = 1
        self.context.scene.frame_end = int(self.first_action.frame_end)
        self.context.scene.render.fps = 30
        self.context.scene.render.fps_base = 1.0
        report = self.remember(bpy.data.texts, bpy.data.texts.new('H3 animation staging report'))
        report.write(json.dumps({'format': 'foundry.h3-animation-staging', 'version': 1,
            'results': self.results, 'node_map': self.mapping, 'pedestal': self.pedestal,
            'notes': ['Source rig and actions unchanged. Staging collection and animations excluded from export.',
                      'Control constraints muted on the staging copy. Events retained, not converted.',
                      'Reach-only bones retain their rest transforms relative to their animated parents.',
                      'JMO frame 1 is the composition reference; frames 2 onward are codec samples.',
                      'Time overlays are standalone composed previews, not NLA layers.',
                      'Blend screens are discrete source-order samples, not timed motion or a runtime aim controller.',
                      'H3 screen metadata is retained; Reach object-space pose-overlay controls are not generated.']}, indent=2))
        self.collection['h3_animation_report'] = report.name
        self.context.view_layer.update()

    def rollback(self):
        if self.context.object and self.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for row in reversed(self.animations):
            for i, existing in enumerate(self.settings.animations):
                if existing == row:
                    self.settings.animations.remove(i)
                    break
        self.animations.clear()
        for store, ob in reversed(self.created):
            try:
                store.remove(ob, do_unlink=True)
            except TypeError:
                store.remove(ob)
            except (ReferenceError, RuntimeError):
                pass
        self.created.clear()

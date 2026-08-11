

import math
import time
from typing import cast
import bpy
from mathutils import Euler, Matrix
from ... import utils

list_source_bones = []
list_root_bones = []

turn_rots = {
    "turn_left": (0, 90),
    "turn_left_slow": (0, 45),
    "turn_left_fast": (0, 360),
    "turn_right": (0, -90),
    "turn_right_slow": (0, -45),
    "turn_right_fast": (0, -360),
}

_AUTOMATIC_MOVEMENT_CHANNELS = {
    # movement type: (location XYZ, rotation XYZ, scale XYZ)
    "none": ((True, True, False), (False, False, True), (False, False, False)),
    "xy": ((True, True, False), (False, False, False), (False, False, False)),
    "xyyaw": ((True, True, False), (False, False, True), (False, False, False)),
    "xyzyaw": ((True, True, True), (False, False, True), (False, False, False)),
    "full": ((True, True, True), (True, True, True), (False, False, False)),
}

last_source_bone = ""
last_root_bone = ""

class NWO_OT_MovementDataToPedestal(bpy.types.Operator):
    bl_idname = "nwo.movement_data_transfer"
    bl_label = "Movement Data Transfer"
    bl_description = "Transfers the movement data of the source bone to the given root bone for the current or all animations. The type of movement transfered depends on the animation movement type"
    bl_options = {"UNDO", "REGISTER"}
    
    @classmethod
    def poll(cls, context):
        return utils.get_scene_props().animations
    
    def items_list_source_bones(self, context):
        return list_source_bones
    
    def items_list_root_bones(self, context):
        return list_root_bones
    
    source_bone: bpy.props.EnumProperty(
        name="Source Bone",
        options={'SKIP_SAVE'},
        description="The source bone that holds the movement to transfer. In the case of a legacy halo character animation this is usually the pelvis",
        items=items_list_source_bones,
    )
    
    root_bone: bpy.props.EnumProperty(
        name="Root Bone",
        options={'SKIP_SAVE'},
        description="The root bone that movement data should be transferred to. This will be the pedestal bone",
        items=items_list_root_bones,
    )
    
    all_animations: bpy.props.BoolProperty(
        name="All Animations",
        description="This operator will run on all animations instead of the currently active one"
    )
    
    include_no_movement: bpy.props.BoolProperty(
        name="Include All Base Animations",
        default=False,
        description="Transfers movement data for no movement base animations. These will be treated as if they have XY yaw movement by default; this will be overridden if the movement data type is set to manual"
    )
    
    movement_type: bpy.props.EnumProperty(
        name="Type",
        description="Determines what transforms are moved from the source bone to the root bone",
        items=[
            ('AUTOMATIC', "Automatic", "Movement type used accounts for the animation movement data type"),
            ('MANUAL', "Manual", "Define the exact type of transforms to move"),
            ('POSE', "Pose", "Uses the root bones current transform and updates keyframes such that the visual animation of the source bone is unchanged"),
            ('ANIMATION', "Animation", "Uses the root bones transform at either the start or end of the specified animation and updates keyframes such that the visual animation of the source bone is unchanged"),
            ('RESET', "Reset", "Resets the root bone to its rest position and updates keyframes such that the visual animation of the source bone is unchanged")
        ]
    )
    
    animation: bpy.props.StringProperty(
        name="Animation",
    )
    
    pose_type: bpy.props.EnumProperty(
        name="Pose Type",
        items=[
            ('CURRENT', 'Current Pose', "Use the current pose as the fixed location of the root bone"),
            ('ANIMATED', "Keyframed Poses", "Use each frame's pose"),
        ]
    )
    
    start_end: bpy.props.EnumProperty(
        name="Frame",
        items=[
            ('START', "Start", "Get the root position from start frame"),
            ('END', "End", "Get the root position from end frame"),
            ('ALL', "All", "Get the root position from every frame"),
        ]
    )
    
    use_x_loc: bpy.props.BoolProperty(
        name="Forward",
        default=True,
        description=""
    )
    use_y_loc: bpy.props.BoolProperty(
        name="Side to Side",
        default=True,
        description=""
    )
    use_z_loc: bpy.props.BoolProperty(
        name="Vertical",
        description=""
    )
    use_x_rot: bpy.props.BoolProperty(
        name="X Rotation",
        description=""
    )
    use_y_rot: bpy.props.BoolProperty(
        name="Y Rotation",
        description=""
    )
    use_z_rot: bpy.props.BoolProperty(
        name="Z Rotation",
        default=True,
        description=""
    )
    use_x_scale: bpy.props.BoolProperty(
        name="X Scale",
        description=""
    )
    use_y_scale: bpy.props.BoolProperty(
        name="Y Scale",
        description=""
    )
    use_z_scale: bpy.props.BoolProperty(
        name="Z Scale",
        description=""
    )
    relative_to_root_start: bpy.props.BoolProperty(
        name="Keep Root Start In Place",
        description="Frame 1 keeps the root bone's existing transform. Later frames receive the selected source transform deltas, and the source bone is counter-keyed so the visible animation stays the same",
        default=True,
    )
    
    relative: bpy.props.BoolProperty(
        name="Relative Source Transforms",
        description="Source positions are tested relative to the root bone (so we'll get the source bone transforms as if they had no parent), otherwise get their final transforms. Toggle this if you're getting weird results!",
        default=False,
    )
    
    def find_armature_ob(self, context) -> bool:
        ob = None
        if context.object and context.object.type == "ARMATURE":
            ob = context.object
        else:
            ob = utils.get_rig(context)

        if ob is None:
            self.report({'WARNING'}, "No armature in scene")
            return False

        global list_root_bones
        list_root_bones = []
        for bone in ob.pose.bones:
            if not bone.parent:
                list_root_bones.append((bone.name, bone.name, ""))

        if not list_root_bones:
            self.report({'WARNING'}, "Armature has no root bone")
            return False

        global list_source_bones
        list_source_bones = []
        for bone in ob.pose.bones:
            if bone.parent:
                list_source_bones.append((bone.name, bone.name, ""))

        if not list_source_bones:
            self.report({'WARNING'}, "Armature has no child bone to use as a movement source")
            return False

        list_source_bones.sort(key=lambda x: "aim" in x[0])  # so aim pitch / aim_yaw don't get sorted first

        self.ob = ob
        return True
    
    def invoke(self, context, event):
        if not self.find_armature_ob(context):
            return {'CANCELLED'}
        for bone in self.ob.pose.bones:
            if bone.name == last_source_bone:
                self.source_bone = last_source_bone
            elif bone.name == last_root_bone:
                self.root_bone = last_root_bone

        return context.window_manager.invoke_props_dialog(self, width=600)
    
    def draw(self, context):
        layout = cast(bpy.types.UILayout, self.layout)
        layout.use_property_split = True
        layout.prop(self, "source_bone")
        layout.prop(self, "root_bone")
        layout.prop(self, "all_animations")
        layout.prop(self, "relative")
        layout.prop(self, "relative_to_root_start")
        layout.prop(self, "movement_type", expand=True)
        if self.movement_type == 'MANUAL':
            layout.prop(self, "use_x_loc")
            layout.prop(self, "use_y_loc")
            layout.prop(self, "use_z_loc")
            layout.prop(self, "use_x_rot")
            layout.prop(self, "use_y_rot")
            layout.prop(self, "use_z_rot")
            layout.prop(self, "use_x_scale")
            layout.prop(self, "use_y_scale")
            layout.prop(self, "use_z_scale")
        elif self.movement_type == 'ANIMATION':
            layout.prop_search(self, "animation", utils.get_scene_props(), "animations", icon='ANIM')
            layout.prop(self, "start_end", expand=True)
        elif self.movement_type == 'AUTOMATIC':
            layout.prop(self, "include_no_movement")
        elif self.movement_type == 'POSE':
            layout.prop(self, "pose_type", expand=True)
        
    def has_movement_data(self, animation) -> bool:
        if animation.animation_type not in {'base', 'world'}:
            return False
        none_movement = animation.animation_movement_data == "none"
        if none_movement:
            if not self.include_no_movement:
                return False
            state = utils.space_partition(animation.name.replace(":", " "), True).lower()
            return state not in {'idle', 'takeoff'}
        
        return True
    
    def execute(self, context):
        global last_source_bone
        global last_root_bone

        scene_nwo = utils.get_scene_props()
        if not scene_nwo.animations:
            self.report({'WARNING'}, "No animations in scene")
            return {'CANCELLED'}

        current_animation_index = scene_nwo.active_animation_index
        current_animation = (
            scene_nwo.animations[current_animation_index]
            if 0 <= current_animation_index < len(scene_nwo.animations)
            else None
        )
        if not self.all_animations and current_animation is None:
            self.report({'WARNING'}, "No active animation")
            return {'CANCELLED'}

        if not self.find_armature_ob(context):
            return {'CANCELLED'}
        if self.source_bone not in self.ob.pose.bones or self.root_bone not in self.ob.pose.bones:
            self.report({'WARNING'}, "The selected source or root bone no longer exists")
            return {'CANCELLED'}

        last_source_bone = self.source_bone
        last_root_bone = self.root_bone

        current_frame = context.scene.frame_current
        current_pose = self.ob.data.pose_position
        current_object = context.object
        current_mode = context.mode

        settings_dict = {}
        root_matrix = None
        try:
            if self.movement_type == 'MANUAL':
                settings_dict = {
                    "use_x_loc": self.use_x_loc,
                    "use_y_loc": self.use_y_loc,
                    "use_z_loc": self.use_z_loc,
                    "use_x_rot": self.use_x_rot,
                    "use_y_rot": self.use_y_rot,
                    "use_z_rot": self.use_z_rot,
                    "use_x_scale": self.use_x_scale,
                    "use_y_scale": self.use_y_scale,
                    "use_z_scale": self.use_z_scale,
                }
                if not any(settings_dict.values()):
                    self.report({'WARNING'}, "No movement channels selected")
                    return {'CANCELLED'}
            elif self.movement_type == 'POSE':
                if self.pose_type == 'CURRENT':
                    root_matrix = self.ob.pose.bones[self.root_bone].matrix.copy()
                else:
                    if current_animation is None or _get_animation_action(current_animation, self.ob) is None:
                        self.report({'WARNING'}, "An active armature animation is required for animated poses")
                        return {'CANCELLED'}
                    root_matrix = get_bone_matrices(
                        context,
                        current_animation_index,
                        current_animation,
                        self.ob.pose.bones[self.root_bone],
                    )
            elif self.movement_type == 'RESET':
                root_matrix = Matrix.Identity(4)
            elif self.movement_type == 'ANIMATION':
                if not self.animation:
                    self.report({'WARNING'}, "No animation specified")
                    return {'CANCELLED'}
                reference_index = next(
                    (idx for idx, animation in enumerate(scene_nwo.animations) if animation.name == self.animation),
                    None,
                )
                if reference_index is None:
                    self.report({'WARNING'}, f"Animation not found: {self.animation}")
                    return {'CANCELLED'}
                reference_animation = scene_nwo.animations[reference_index]
                if _get_animation_action(reference_animation, self.ob) is None:
                    self.report({'WARNING'}, f"Animation has no action for {self.ob.name}: {self.animation}")
                    return {'CANCELLED'}
                _activate_animation(scene_nwo, reference_index)
                if self.start_end == 'START':
                    context.scene.frame_set(reference_animation.frame_start)
                    root_matrix = self.ob.pose.bones[self.root_bone].matrix.copy()
                elif self.start_end == 'END':
                    context.scene.frame_set(reference_animation.frame_end)
                    root_matrix = self.ob.pose.bones[self.root_bone].matrix.copy()
                else:
                    root_matrix = get_bone_matrices(
                        context,
                        reference_index,
                        reference_animation,
                        self.ob.pose.bones[self.root_bone],
                    )
        finally:
            if scene_nwo.active_animation_index != current_animation_index:
                scene_nwo.active_animation_index = current_animation_index
            context.scene.frame_set(current_frame)

        candidate_indices = (
            range(len(scene_nwo.animations))
            if self.all_animations
            else (current_animation_index,)
        )
        target_indices = []
        for idx in candidate_indices:
            animation = scene_nwo.animations[idx]
            if self.movement_type == 'AUTOMATIC' and not self.has_movement_data(animation):
                continue
            if _get_animation_action(animation, self.ob) is None:
                if self.all_animations:
                    print(f"Skipping {animation.name}: no action for {self.ob.name}")
                continue
            target_indices.append(idx)

        if not target_indices:
            self.report({'WARNING'}, "No eligible armature animations found")
            return {'CANCELLED'}

        utils.set_object_mode(context)
        utils.set_active_object(self.ob)

        start = time.perf_counter()
        if self.all_animations:
            print("MOVEMENT DATA TRANSFER\n")

        source_bone = self.ob.pose.bones[self.source_bone]
        source_data_bone = self.ob.data.bones[self.source_bone]
        original_parent_name = source_data_bone.parent.name if source_data_bone.parent else None
        original_use_connect = source_data_bone.use_connect
        source_bone_anim_matrices = {}
        transfer_masks = {}
        hierarchy_changed = False

        try:
            if not self.relative:
                print("Getting existing source bone poses")
                for idx in target_indices:
                    animation = scene_nwo.animations[idx]
                    print(f"--- {animation.name}")
                    source_bone_anim_matrices[idx] = get_bone_matrices(context, idx, animation, source_bone)

            self.ob.data.pose_position = 'REST'
            context.view_layer.update()
            root_rest_matrix = self.ob.pose.bones[self.root_bone].matrix.copy()

            hierarchy_changed = True
            _set_source_parent(self.ob, self.source_bone, None, False)
            self.ob.data.pose_position = 'POSE'
            context.view_layer.update()

            if self.movement_type == 'RESET':
                root_matrix = root_rest_matrix

            if self.relative:
                print("Getting existing source bone poses")
                for idx in target_indices:
                    animation = scene_nwo.animations[idx]
                    print(f"--- {animation.name}")
                    source_bone_anim_matrices[idx] = get_bone_matrices(context, idx, animation, source_bone)

            print("Calculating new root movement")
            for idx in target_indices:
                animation = scene_nwo.animations[idx]
                print(f"--- {animation.name}")
                transfer_masks[idx] = transfer_movement(
                    context,
                    animation,
                    idx,
                    self.ob,
                    self.source_bone,
                    self.root_bone,
                    root_rest_matrix,
                    root_matrix,
                    settings_dict,
                    source_bone_anim_matrices[idx],
                    self.relative_to_root_start,
                )

            _set_source_parent(
                self.ob,
                self.source_bone,
                original_parent_name,
                original_use_connect,
            )
            hierarchy_changed = False
            self.ob.data.pose_position = 'POSE'
            context.view_layer.update()

            print("\nSetting new source bone keyframes")
            for idx in target_indices:
                animation = scene_nwo.animations[idx]
                print(f"--- {animation.name}")
                use_loc, use_rot, use_scale = transfer_masks[idx]
                fix_source_movement(
                    context,
                    animation,
                    idx,
                    self.ob,
                    self.source_bone,
                    source_bone_anim_matrices[idx],
                    key_location=any(use_loc) or any(use_rot) or any(use_scale),
                    key_rotation=any(use_rot) or any(use_scale),
                    key_scale=any(use_scale),
                )
        finally:
            if hierarchy_changed:
                utils.set_object_mode(context)
                utils.set_active_object(self.ob)
                _set_source_parent(
                    self.ob,
                    self.source_bone,
                    original_parent_name,
                    original_use_connect,
                )

            self.ob.data.pose_position = current_pose
            if scene_nwo.active_animation_index != current_animation_index:
                scene_nwo.active_animation_index = current_animation_index
            context.scene.frame_set(current_frame)
            active_object = context.view_layer.objects.get(current_object.name) if current_object else None
            context.view_layer.objects.active = active_object
            if active_object is not None:
                utils.restore_mode(current_mode)

        if self.all_animations:
            print("\n-----------------------------------------------------------------------")
            print(f"Completed in {utils.human_time(time.perf_counter() - start, True)}")
            print("-----------------------------------------------------------------------\n")

        return {'FINISHED'}
    
def _get_animation_action(animation, ob: bpy.types.Object) -> bpy.types.Action | None:
    actions = [
        track.action
        for track in animation.action_tracks
        if track.object == ob and track.action is not None and not track.is_shape_key_action
    ]
    if not actions:
        return None

    active_action = ob.animation_data.action if ob.animation_data else None
    return active_action if active_action in actions else actions[0]


def _activate_animation(scene_nwo, animation_index: int):
    if scene_nwo.active_animation_index != animation_index:
        scene_nwo.active_animation_index = animation_index


def _set_source_parent(
    ob: bpy.types.Object,
    source_bone_name: str,
    parent_bone_name: str | None,
    use_connect: bool,
):
    bpy.ops.object.mode_set(mode='EDIT', toggle=False)
    try:
        source_bone = ob.data.edit_bones[source_bone_name]
        source_bone.use_connect = False
        source_bone.parent = ob.data.edit_bones.get(parent_bone_name) if parent_bone_name else None
        source_bone.use_connect = bool(parent_bone_name and use_connect)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)


def _fit_matrix_sequence(matrices: list[Matrix], frame_count: int) -> list[Matrix]:
    if frame_count <= 0:
        return []
    if not matrices:
        raise ValueError("Cannot fit an empty matrix sequence")
    if len(matrices) >= frame_count:
        return list(matrices[:frame_count])
    return list(matrices) + [matrices[-1]] * (frame_count - len(matrices))


def get_bone_matrices(
    context: bpy.types.Context,
    animation_index: int,
    animation,
    bone: bpy.types.PoseBone,
) -> list[Matrix]:
    scene_nwo = utils.get_scene_props()
    _activate_animation(scene_nwo, animation_index)
    bone_matrices = []
    for frame in range(animation.frame_start, animation.frame_end + 1):
        context.scene.frame_set(frame)
        bone_matrices.append(bone.matrix.copy())
    return bone_matrices


def _transform_sample_from_pose_matrix(
    ob: bpy.types.Object,
    bone: bpy.types.PoseBone,
    frame: int,
    pose_matrix: Matrix,
    previous_rotation: tuple[float, float, float, float] | None,
):
    local_matrix = ob.convert_space(
        pose_bone=bone,
        matrix=pose_matrix,
        from_space='POSE',
        to_space='LOCAL',
    )
    location, rotation, scale = local_matrix.decompose()
    rotation_values = (rotation.w, rotation.x, rotation.y, rotation.z)
    if previous_rotation is not None:
        dot = sum(a * b for a, b in zip(rotation_values, previous_rotation))
        if dot < 0:
            rotation_values = tuple(-value for value in rotation_values)

    sample = (
        frame,
        (location.x, location.y, location.z),
        rotation_values,
        (scale.x, scale.y, scale.z),
    )
    return sample, rotation_values


def _transform_samples_from_pose_matrices(
    ob: bpy.types.Object,
    bone: bpy.types.PoseBone,
    frames: range,
    pose_matrices: list[Matrix],
):
    samples = []
    previous_rotation = None
    for frame, pose_matrix in zip(frames, pose_matrices):
        sample, previous_rotation = _transform_sample_from_pose_matrix(
            ob,
            bone,
            frame,
            pose_matrix,
            previous_rotation,
        )
        samples.append(sample)
    return samples


def _write_transform_samples(
    animation,
    ob: bpy.types.Object,
    bone: bpy.types.PoseBone,
    samples,
    key_location: bool,
    key_rotation: bool,
    key_scale: bool,
):
    if not samples or not (key_location or key_rotation or key_scale):
        return

    action = _get_animation_action(animation, ob)
    if action is None:
        raise RuntimeError(f"Animation {animation.name} has no action for {ob.name}")

    fcurves = utils.get_fcurves(action, ob)
    if fcurves is None:
        raise RuntimeError(f"Could not find the action slot for {action.name}")

    curve_map = {(fcurve.data_path, fcurve.array_index): fcurve for fcurve in fcurves}
    channels = []
    if key_location:
        channels.append(("location", 3, 1))
    if key_rotation:
        channels.append(("rotation_quaternion", 4, 2))
    if key_scale:
        channels.append(("scale", 3, 3))

    for channel, component_count, sample_index in channels:
        data_path = f'pose.bones["{bone.name}"].{channel}'
        for component in range(component_count):
            key = (data_path, component)
            fcurve = curve_map.get(key)
            if fcurve is None:
                fcurve = fcurves.new(data_path=data_path, index=component)
                curve_map[key] = fcurve

            points_by_frame = {float(point.co[0]): point for point in fcurve.keyframe_points}
            for sample in samples:
                frame = float(sample[0])
                value = sample[sample_index][component]
                point = points_by_frame.get(frame)
                if point is None:
                    point = fcurve.keyframe_points.insert(frame, value, options={'FAST'})
                    points_by_frame[frame] = point
                else:
                    point.co_ui[1] = value
                # These are baked per-frame samples. Linear interpolation prevents
                # Bezier handles from introducing motion that was never sampled.
                point.interpolation = 'LINEAR'
            fcurve.update()

    action.update_tag()


def fix_source_movement(
    context: bpy.types.Context,
    animation,
    animation_index: int,
    ob: bpy.types.Object,
    source_bone_name: str,
    source_bone_matrices: list[Matrix],
    key_location: bool,
    key_rotation: bool,
    key_scale: bool,
):
    scene_nwo = utils.get_scene_props()
    _activate_animation(scene_nwo, animation_index)
    source_bone = ob.pose.bones[source_bone_name]
    frames = range(animation.frame_start, animation.frame_end + 1)
    fitted_matrices = _fit_matrix_sequence(source_bone_matrices, len(frames))

    samples = []
    previous_rotation = None
    for frame, pose_matrix in zip(frames, fitted_matrices):
        context.scene.frame_set(frame)
        sample, previous_rotation = _transform_sample_from_pose_matrix(
            ob,
            source_bone,
            frame,
            pose_matrix,
            previous_rotation,
        )
        samples.append(sample)

    _write_transform_samples(
        animation,
        ob,
        source_bone,
        samples,
        key_location,
        key_rotation,
        key_scale,
    )


def _movement_channel_masks(
    animation,
    custom_settings: dict | None,
    root_matrix: Matrix | list[Matrix] | None,
):
    """Returns (use_loc, use_rot, use_scale, special_turn, final_token)."""
    special_turn = False
    final_token = ""

    if custom_settings:
        return (
            (
                custom_settings.get("use_x_loc", False),
                custom_settings.get("use_y_loc", False),
                custom_settings.get("use_z_loc", False),
            ),
            (
                custom_settings.get("use_x_rot", False),
                custom_settings.get("use_y_rot", False),
                custom_settings.get("use_z_rot", False),
            ),
            (
                custom_settings.get("use_x_scale", False),
                custom_settings.get("use_y_scale", False),
                custom_settings.get("use_z_scale", False),
            ),
            False,
            final_token,
        )

    if root_matrix is not None:
        return (True, True, True), (True, True, True), (True, True, True), False, final_token

    if animation.animation_type == 'world':
        return (True, True, True), (True, True, True), (False, False, False), False, final_token

    use_loc, use_rot, use_scale = _AUTOMATIC_MOVEMENT_CHANNELS[animation.animation_movement_data]
    if use_rot == (False, False, True):
        final_token = utils.space_partition(animation.name.replace(":", " "), True).lower()
        special_turn = final_token in turn_rots

    return use_loc, use_rot, use_scale, special_turn, final_token


def _compose_selected_delta_matrix(
    source_matrix: Matrix,
    source_start_matrix: Matrix,
    root_start_matrix: Matrix,
    use_loc: tuple[bool, bool, bool],
    use_rot: tuple[bool, bool, bool],
    use_scale: tuple[bool, bool, bool],
) -> Matrix:
    wanted_follow_matrix = source_matrix @ source_start_matrix.inverted_safe() @ root_start_matrix
    return _compose_selected_absolute_matrix(
        root_start_matrix,
        wanted_follow_matrix,
        use_loc,
        use_rot,
        use_scale,
    )


def _compose_selected_absolute_matrix(
    existing_matrix: Matrix,
    incoming_matrix: Matrix,
    use_loc: tuple[bool, bool, bool],
    use_rot: tuple[bool, bool, bool],
    use_scale: tuple[bool, bool, bool],
) -> Matrix:
    existing_loc, existing_rot, existing_scale = existing_matrix.decompose()
    incoming_loc, incoming_rot, incoming_scale = incoming_matrix.decompose()

    loc = existing_loc.copy()
    for axis, use_axis in enumerate(use_loc):
        if use_axis:
            loc[axis] = incoming_loc[axis]

    if all(use_rot):
        rot = incoming_rot
    elif any(use_rot):
        euler_order = existing_rot.to_euler().order
        existing_euler = existing_rot.to_euler(euler_order)
        incoming_euler = incoming_rot.to_euler(euler_order)
        for axis, use_axis in enumerate(use_rot):
            if use_axis:
                existing_euler[axis] = incoming_euler[axis]
        rot = existing_euler.to_quaternion()
    else:
        rot = existing_rot

    scale = existing_scale.copy()
    for axis, use_axis in enumerate(use_scale):
        if use_axis:
            scale[axis] = incoming_scale[axis]

    return Matrix.LocRotScale(loc, rot, scale)


def _special_turn_angles(source_matrices: list[Matrix], final_token: str) -> list[float]:
    turn_start, turn_end = turn_rots[final_token]
    frame_count = len(source_matrices)
    if frame_count <= 1:
        return [math.radians(turn_start)] * frame_count

    # Old turn animations are not guaranteed to rotate cleanly in one direction.
    # Drive the requested turn from accumulated yaw travel so reversals, overshoot,
    # and a source endpoint near its start cannot reverse or amplify the pedestal.
    yaw_travel = [0.0]
    previous_rotation = source_matrices[0].to_quaternion()
    for matrix in source_matrices[1:]:
        current_rotation = matrix.to_quaternion()
        delta_rotation = current_rotation @ previous_rotation.inverted()
        _, twist_angle = delta_rotation.to_swing_twist('Z')
        yaw_travel.append(yaw_travel[-1] + abs(twist_angle))
        previous_rotation = current_rotation

    total_travel = yaw_travel[-1]
    if total_travel < 1e-8:
        factors = [index / (frame_count - 1) for index in range(frame_count)]
    else:
        factors = [travel / total_travel for travel in yaw_travel]

    turn_delta = turn_end - turn_start
    return [math.radians(turn_start + turn_delta * factor) for factor in factors]


def _apply_special_turn(
    matrix: Matrix,
    base_rotation: Euler,
    turn_angle: float,
) -> Matrix:
    location, _, scale = matrix.decompose()
    rotation = Euler((0, 0, turn_angle))
    rotation.rotate(base_rotation)
    return Matrix.LocRotScale(location, rotation, scale)


def _add_copy_constraint(
    root_bone: bpy.types.PoseBone,
    ob: bpy.types.Object,
    source_bone_name: str,
    constraint_type: str,
    axes: tuple[bool, bool, bool],
):
    if not any(axes):
        return None

    constraint = root_bone.constraints.new(type=constraint_type)
    constraint.target = ob
    constraint.subtarget = source_bone_name
    constraint.target_space = 'LOCAL_OWNER_ORIENT'
    constraint.owner_space = 'LOCAL'
    constraint.use_x, constraint.use_y, constraint.use_z = axes
    return constraint


def transfer_movement(
    context: bpy.types.Context,
    animation,
    animation_index: int,
    ob: bpy.types.Object,
    source_bone_name: str,
    root_bone_name: str,
    root_rest_matrix: Matrix,
    root_matrix: Matrix | list[Matrix] | None,
    custom_settings: dict | None = None,
    source_bone_matrices: list[Matrix] | None = None,
    relative_to_root_start: bool = True,
):
    scene_nwo = utils.get_scene_props()
    _activate_animation(scene_nwo, animation_index)

    root_bone = ob.pose.bones[root_bone_name]
    use_loc, use_rot, use_scale, special_turn, final_token = _movement_channel_masks(
        animation,
        custom_settings,
        root_matrix,
    )
    masks = (use_loc, use_rot, use_scale)
    use_root_transform = root_matrix is not None
    frames = range(animation.frame_start, animation.frame_end + 1)
    frame_count = len(frames)
    fitted_source_matrices = _fit_matrix_sequence(source_bone_matrices or [], frame_count)

    if relative_to_root_start and not use_root_transform:
        context.scene.frame_set(animation.frame_start)
        root_start_matrix = root_bone.matrix.copy()
        source_start_matrix = fitted_source_matrices[0]
        source_rotation_mask = (
            (use_rot[0], use_rot[1], False)
            if special_turn
            else use_rot
        )
        target_matrices = [
            _compose_selected_delta_matrix(
                source_matrix,
                source_start_matrix,
                root_start_matrix,
                use_loc,
                source_rotation_mask,
                use_scale,
            )
            for source_matrix in fitted_source_matrices
        ]

        if special_turn:
            base_rotation = root_start_matrix.to_euler()
            target_matrices = [
                _apply_special_turn(matrix, base_rotation, angle)
                for matrix, angle in zip(
                    target_matrices,
                    _special_turn_angles(fitted_source_matrices, final_token),
                )
            ]

        samples = _transform_samples_from_pose_matrices(
            ob,
            root_bone,
            frames,
            target_matrices,
        )
        _write_transform_samples(
            animation,
            ob,
            root_bone,
            samples,
            any(use_loc),
            any(use_rot),
            any(use_scale),
        )
        return masks

    if use_root_transform:
        if isinstance(root_matrix, Matrix):
            incoming_matrices = [root_matrix] * frame_count
        else:
            incoming_matrices = _fit_matrix_sequence(root_matrix, frame_count)

        if all(use_loc) and all(use_rot) and all(use_scale):
            target_matrices = list(incoming_matrices)
        else:
            target_matrices = []
            for frame, incoming_matrix in zip(frames, incoming_matrices):
                context.scene.frame_set(frame)
                target_matrices.append(
                    _compose_selected_absolute_matrix(
                        root_bone.matrix.copy(),
                        incoming_matrix,
                        use_loc,
                        use_rot,
                        use_scale,
                    )
                )

        samples = _transform_samples_from_pose_matrices(
            ob,
            root_bone,
            frames,
            target_matrices,
        )
        _write_transform_samples(
            animation,
            ob,
            root_bone,
            samples,
            any(use_loc),
            any(use_rot),
            any(use_scale),
        )
        return masks

    constraints = []
    source_rotation_mask = (
        (use_rot[0], use_rot[1], False)
        if special_turn
        else use_rot
    )
    try:
        for constraint_type, axes in (
            ('COPY_LOCATION', use_loc),
            ('COPY_ROTATION', source_rotation_mask),
            ('COPY_SCALE', use_scale),
        ):
            constraint = _add_copy_constraint(
                root_bone,
                ob,
                source_bone_name,
                constraint_type,
                axes,
            )
            if constraint is not None:
                constraints.append(constraint)

        special_angles = (
            _special_turn_angles(fitted_source_matrices, final_token)
            if special_turn
            else None
        )
        base_rotation = root_rest_matrix.to_euler()
        samples = []
        previous_rotation = None
        for index, frame in enumerate(frames):
            context.scene.frame_set(frame)
            pose_matrix = root_bone.matrix.copy()
            if special_angles is not None:
                pose_matrix = _apply_special_turn(
                    pose_matrix,
                    base_rotation,
                    special_angles[index],
                )
            sample, previous_rotation = _transform_sample_from_pose_matrix(
                ob,
                root_bone,
                frame,
                pose_matrix,
                previous_rotation,
            )
            samples.append(sample)
    finally:
        for constraint in reversed(constraints):
            root_bone.constraints.remove(constraint)

    _write_transform_samples(
        animation,
        ob,
        root_bone,
        samples,
        any(use_loc),
        any(use_rot),
        any(use_scale),
    )
    return masks


class FCurveTransfer:
    source_fcurve: bpy.types.FCurve
    target_fcurve: bpy.types.FCurve
    
    def __init__(self, action: bpy.types.Action, source_bone: str, target_bone: str, source_channel: str, target_channel: str, slot_name: str) -> None:
        source_channel_array_index, source_channel_name = source_channel.split(':')
        target_channel_array_index, target_channel_name = target_channel.split(':')
        self.action = action
        self.fcurves = utils.get_fcurves(self.action, slot_name)
        self.source_bone = source_bone
        self.target_bone = target_bone
        self.source_channel = source_channel_name
        self.source_channel_index = int(source_channel_array_index)
        self.target_channel_index = int(target_channel_array_index)
        self.target_channel = target_channel_name
        self.source_fcurve = None
        self.target_fcurve = None
    
    def get_fcurves(self):
        source_data_path = f'pose.bones["{self.source_bone}"].{self.source_channel}'
        target_data_path = f'pose.bones["{self.target_bone}"].{self.target_channel}'
        for fc in self.fcurves:
            if fc.data_path == source_data_path and fc.array_index == self.source_channel_index:
                self.source_fcurve = fc
            elif fc.data_path == target_data_path and fc.array_index == self.target_channel_index:
                self.target_fcurve = fc
                
        if not self.source_fcurve:
            return
        
        if not self.target_fcurve:
            self.target_fcurve = self.fcurves.new(data_path=f'pose.bones["{self.target_bone}"].{self.target_channel}', index=self.target_channel_index)
            
    def transfer_data(self):
        source_coordinates = []
        for kfp in self.source_fcurve.keyframe_points:
            source_coordinates.append(kfp.co_ui[1])
            
        target_kfps = self.target_fcurve.keyframe_points
        for index, coordinates in enumerate(source_coordinates):
            target_kfps.insert(index, coordinates, options={'REPLACE'})
            
    def remove_source_fcurve(self):
        self.fcurves.remove(self.source_fcurve)
            
class NWO_OT_FcurveTransfer(bpy.types.Operator):
    bl_idname = "nwo.fcurve_transfer"
    bl_label = "Motion Transfer"
    bl_description = "Transfers animation keyframes from one channel to another. For example transferring all motion on the Z location channel of bone A to the X location channel of bone B"
    bl_options = {"UNDO", "REGISTER"}
    
    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == 'ARMATURE'
    
    all_animations: bpy.props.BoolProperty(
        name="All Animations",
        description="Run this operator on all actions in the blend file. Disable to only run on the active animation",
    )
    
    remove_source_data: bpy.props.BoolProperty(
        name="Remove Source Channel",
        description="Removes all data from the source channel after transfer",
        default=True,
    )
    
    def list_bones(self, context):
        items = []
        arm = context.object
        for bone in arm.pose.bones:
            items.append((bone.name, bone.name, ""))
            
        return items
            
    def list_channels(self, context):
        items = [
            ("0:location", "X Location", ""),
            ("1:location", "Y Location", ""),
            ("2:location", "Z Location", ""),
            ("0:rotation_euler", "X Euler", ""),
            ("1:rotation_euler", "Y Euler", ""),
            ("2:rotation_euler", "Z Euler", ""),
            ("0:rotation_quaternion", "W Quaternion", ""),
            ("1:rotation_quaternion", "X Quaternion", ""),
            ("2:rotation_quaternion", "Y Quaternion", ""),
            ("3:rotation_quaternion", "Z Quaternion", ""),
            ("0:scale", "X Scale", ""),
            ("1:scale", "Y Scale", ""),
            ("2:scale", "Z Scale", ""),
        ]
        
        return items
    
    source_bone: bpy.props.EnumProperty(
        name="Source Bone",
        description="The bone to transfer data from",
        items=list_bones,
    )
    
    source_channel: bpy.props.EnumProperty(
        name="Source Channel",
        description="The name of the channel containing data. This data must exist",
        items=list_channels,
    )
    
    target_bone: bpy.props.EnumProperty(
        name="Target Bone",
        description="The bone to transfer data to",
        items=list_bones,
    )
    
    target_channel: bpy.props.EnumProperty(
        name="Target Channel",
        description="The name of the channel to receive data. This can be empty",
        items=list_channels,
    )

    def execute(self, context):
        scene_nwo = utils.get_scene_props()
        active_animation_index = scene_nwo.active_animation_index
        animation = scene_nwo.animations[active_animation_index]
        actions = []
        if self.all_animations:
            actions = set(bpy.data.actions)
        else:
            actions = {track.action for track in animation.action_tracks}
            
        armature = context.object
        if not armature.animation_data:
            armature.animation_data_create()
            
        slot_name = armature.animation_data.last_slot_identifier
            
        utils.clear_animation(animation)
        for action in actions:
            fcurve_transfer = FCurveTransfer(action, self.source_bone, self.target_bone, self.source_channel, self.target_channel, slot_name)
            fcurve_transfer.get_fcurves()
            if fcurve_transfer.source_fcurve:
                fcurve_transfer.transfer_data()
                if self.remove_source_data:
                    fcurve_transfer.remove_source_fcurve()
            else:
                self.report({'WARNING'}, f"Failed to find source fcurve on action {action.name}")
        
        scene_nwo.active_animation_index = active_animation_index
        return {"FINISHED"}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "source_bone")
        layout.prop(self, "source_channel")
        layout.separator()
        layout.prop(self, "target_bone")
        layout.prop(self, "target_channel")
        layout.separator()
        layout.prop(self, "all_animations")
        layout.prop(self, "remove_source_data")

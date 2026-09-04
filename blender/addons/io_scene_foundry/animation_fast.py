import builtins
from collections import defaultdict
from contextlib import contextmanager
from math import ceil, floor
from time import perf_counter

import bpy

from . import foundry_output, utils
from .managed_blam import animation as animation_module
from .tools import importer as importer_module
from .tools.rigging import create_rig as create_rig_module
from .ui.panel import NWO_FoundryPanelProps


_original_to_blender = None
_original_events_to_blender = None
_original_generate_renames = None
_original_importer_bake = None
_original_importer_init = None
_original_draw_animation_manager = None
_original_bake_control_rig_actions = None
_original_blender_bake_action = None
_original_correct_baked_ik_target_actions = None
_original_correct_baked_head_look_target_actions = None
_original_set_control_rig_inverted = None
_original_bake_annotations = []
_menu_types = []
_bake_profiles = []


def _detail_print(message):
    foundry_output.print_detail(message)


def _format_print(args, sep, end):
    text = sep.join(str(arg) for arg in args)
    if end and end not in {"\n", "\r\n"}:
        text += end
    return text.rstrip("\r\n")


@contextmanager
def _route_animation_details(route_step=False, route_bullet=False, live_prefixes=()):
    had_module_print = "print" in animation_module.__dict__
    old_module_print = animation_module.__dict__.get("print")
    old_step = utils.print_step
    old_bullet = utils.print_bullet

    def module_print(*args, sep=" ", end="\n", file=None, flush=False):
        text = _format_print(args, sep, end)
        if any(text.startswith(prefix) for prefix in live_prefixes):
            return builtins.print(*args, sep=sep, end=end, file=file, flush=flush)
        _detail_print(text)

    animation_module.print = module_print
    if route_step:
        utils.print_step = lambda message: _detail_print(f"  - {message}")
    if route_bullet:
        utils.print_bullet = lambda message: _detail_print(f"• {message}")

    try:
        yield
    finally:
        if had_module_print:
            animation_module.print = old_module_print
        else:
            animation_module.__dict__.pop("print", None)
        utils.print_step = old_step
        utils.print_bullet = old_bullet


@contextmanager
def _route_control_rig_details():
    had_print = "print" in create_rig_module.__dict__
    old_print = create_rig_module.__dict__.get("print")

    def module_print(*args, sep=" ", end="\n", file=None, flush=False):
        _detail_print(_format_print(args, sep, end))

    create_rig_module.print = module_print
    try:
        yield
    finally:
        if had_print:
            create_rig_module.print = old_print
        else:
            create_rig_module.__dict__.pop("print", None)


def _animation_count(result):
    if not isinstance(result, tuple) or not result:
        return 0
    actions = result[0]
    try:
        return len(actions)
    except TypeError:
        return 0


def _to_blender(self, *args, **kwargs):
    start = perf_counter()
    with _route_animation_details(route_step=True):
        result = _original_to_blender(self, *args, **kwargs)
    print(f"[Foundry perf] Animation import: {perf_counter() - start:.3f}s ({_animation_count(result)} animations)")
    return result


def _events_to_blender(self, *args, **kwargs):
    start = perf_counter()
    with _route_animation_details(route_step=True, route_bullet=True):
        result = _original_events_to_blender(self, *args, **kwargs)
    count = result if isinstance(result, int) else 0
    print(f"[Foundry perf] Frame events: {perf_counter() - start:.3f}s ({count} events)")
    return result


def _generate_renames(self, *args, **kwargs):
    start = perf_counter()
    with _route_animation_details(live_prefixes=("Generated ",)):
        result = _original_generate_renames(self, *args, **kwargs)
    print(f"[Foundry perf] Animation renames: {perf_counter() - start:.3f}s")
    return result


def _current_bake_profile():
    return _bake_profiles[-1] if _bake_profiles else None


def _profile_call(label, original, *args, **kwargs):
    profile = _current_bake_profile()
    if profile is None:
        return original(*args, **kwargs)

    started = perf_counter()
    try:
        return original(*args, **kwargs)
    finally:
        profile["timings"][label] += perf_counter() - started
        profile["calls"][label] += 1


def _profiled_blender_bake_action(*args, **kwargs):
    return _profile_call("blender bake_action", _original_blender_bake_action, *args, **kwargs)


def _profiled_bake_control_rig_actions(*args, **kwargs):
    return _profile_call("control bake", _original_bake_control_rig_actions, *args, **kwargs)


def _profiled_correct_baked_ik_target_actions(*args, **kwargs):
    return _profile_call("ik pole correction", _original_correct_baked_ik_target_actions, *args, **kwargs)


def _profiled_correct_baked_head_look_target_actions(*args, **kwargs):
    return _profile_call("head look correction", _original_correct_baked_head_look_target_actions, *args, **kwargs)


def _profiled_set_control_rig_inverted(*args, **kwargs):
    return _profile_call("rig inversion", _original_set_control_rig_inverted, *args, **kwargs)


def _action_frame_count(action, armature):
    try:
        start, end = utils.get_frame_start_end_from_keyframes(action, armature)
    except Exception:
        return 0
    if end < start:
        return 0
    return max(0, ceil(end) - floor(start) + 1)


def _print_bake_profile(profile, total):
    timings = profile["timings"]
    frame_count = profile["frames"]
    action_count = profile["actions"]
    action_word = "action" if action_count == 1 else "actions"

    control_total = timings.get("control bake", 0.0)
    blender_bake = timings.get("blender bake_action", 0.0)
    bake_setup = max(0.0, control_total - blender_bake)
    ik_pole = timings.get("ik pole correction", 0.0)
    head_look = timings.get("head look correction", 0.0)
    inversion = timings.get("rig inversion", 0.0)
    other = max(0.0, total - control_total - ik_pole - head_look - inversion)

    print(f"[Foundry perf] Control rig bake: {total:.3f}s ({action_count} {action_word}, {frame_count} frames)")
    stages = [
        ("Blender visual bake", blender_bake),
        ("Bake setup / restore", bake_setup),
        ("IK / pole correction", ik_pole),
        ("Head / look correction", head_look),
        ("Rig inversion", inversion),
        ("Other setup / updates", other),
    ]

    for label, elapsed in stages:
        if elapsed <= 0.0005:
            continue
        percent = elapsed / total * 100.0 if total > 0.0 else 0.0
        if frame_count:
            per_frame = elapsed / frame_count * 1000.0
            print(f"  {label:<24} {elapsed:8.3f}s  {percent:6.1f}%  {per_frame:8.2f} ms/frame")
        else:
            print(f"  {label:<24} {elapsed:8.3f}s  {percent:6.1f}%")


def _bake_actions(context, armature, actions):
    actions = list(dict.fromkeys(action for action in actions if action is not None))
    if not actions:
        return 0

    frame_counts = [(action.name, _action_frame_count(action, armature)) for action in actions]
    profile = {
        "actions": len(actions),
        "frames": sum(count for _name, count in frame_counts),
        "timings": defaultdict(float),
        "calls": defaultdict(int),
    }
    for name, count in frame_counts:
        _detail_print(f"Control rig bake action: {name} ({count} frames)")

    _bake_profiles.append(profile)
    started = perf_counter()
    try:
        with _route_control_rig_details():
            result = _original_importer_bake(context, armature, actions)
    finally:
        total = perf_counter() - started
        if _bake_profiles and _bake_profiles[-1] is profile:
            _bake_profiles.pop()
        else:
            try:
                _bake_profiles.remove(profile)
            except ValueError:
                pass
        _print_bake_profile(profile, total)
    return result


def _importer_init(self, *args, **kwargs):
    _original_importer_init(self, *args, **kwargs)
    self.graph_bake_to_control_rig = False


def _active_animation_action(context):
    scene_nwo = utils.get_scene_props()
    animations = scene_nwo.animations
    index = scene_nwo.active_animation_index
    if animations and 0 <= index < len(animations):
        animation = animations[index]
        for track in animation.action_tracks:
            if track.object is not None and track.object.type == "ARMATURE" and track.action is not None and not track.is_shape_key_action:
                return track.object, track.action

    armature = utils.get_rig_prioritize_active(context)
    if armature is None or armature.animation_data is None:
        return None, None
    return armature, armature.animation_data.action


class NWO_OT_BakeActiveAnimationToControlRig(bpy.types.Operator):
    bl_idname = "nwo.bake_active_animation_to_control_rig"
    bl_label = "Bake Active Animation to Control Rig"
    bl_description = "Bake only the active animation to the existing FK/IK control rig"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        armature, action = _active_animation_action(context)
        return armature is not None and action is not None and create_rig_module.armature_has_control_rig(armature)

    def execute(self, context):
        armature, action = _active_animation_action(context)
        if armature is None or action is None:
            self.report({"WARNING"}, "No active armature animation")
            return {"CANCELLED"}
        if not create_rig_module.armature_has_control_rig(armature):
            self.report({"WARNING"}, "Build a control rig first")
            return {"CANCELLED"}

        baked = _bake_actions(context, armature, [action])
        if baked:
            self.report({"INFO"}, f"Baked {action.name} to the control rig")
            return {"FINISHED"}

        self.report({"WARNING"}, "Animation was not baked")
        return {"CANCELLED"}


def _draw_action_menu(self, context):
    self.layout.separator()
    self.layout.operator(NWO_OT_BakeActiveAnimationToControlRig.bl_idname)


def _draw_animation_manager(self):
    _original_draw_animation_manager(self)
    try:
        row = self.box.row(align=True)
        row.operator(
            NWO_OT_BakeActiveAnimationToControlRig.bl_idname,
            text="Bake Active to Control Rig",
            icon="ARMATURE_DATA",
        )
    except Exception:
        pass


def _set_bake_default_off():
    description = "Bakes imported animations to an existing or newly built control rig. Expensive for full animation graphs"
    for value in vars(importer_module).values():
        annotations = getattr(value, "__annotations__", None)
        if not isinstance(value, type) or not annotations or "graph_bake_to_control_rig" not in annotations:
            continue
        original = annotations["graph_bake_to_control_rig"]
        _original_bake_annotations.append((value, original))
        annotations["graph_bake_to_control_rig"] = bpy.props.BoolProperty(
            name="Bake to Control Rig",
            default=False,
            description=description,
        )


def register():
    global _original_to_blender
    global _original_events_to_blender
    global _original_generate_renames
    global _original_importer_bake
    global _original_importer_init
    global _original_draw_animation_manager
    global _original_bake_control_rig_actions
    global _original_blender_bake_action
    global _original_correct_baked_ik_target_actions
    global _original_correct_baked_head_look_target_actions
    global _original_set_control_rig_inverted

    _set_bake_default_off()

    _original_importer_init = importer_module.NWOImporter.__init__
    importer_module.NWOImporter.__init__ = _importer_init

    _original_to_blender = animation_module.AnimationTag.to_blender
    _original_events_to_blender = animation_module.AnimationTag.events_to_blender
    _original_generate_renames = animation_module.AnimationTag.generate_renames
    animation_module.AnimationTag.to_blender = _to_blender
    animation_module.AnimationTag.events_to_blender = _events_to_blender
    animation_module.AnimationTag.generate_renames = _generate_renames

    _original_bake_control_rig_actions = create_rig_module.bake_control_rig_actions
    _original_blender_bake_action = create_rig_module.anim_utils.bake_action
    _original_correct_baked_ik_target_actions = create_rig_module.correct_baked_ik_target_actions
    _original_correct_baked_head_look_target_actions = create_rig_module.correct_baked_head_look_target_actions
    _original_set_control_rig_inverted = create_rig_module.set_control_rig_inverted
    create_rig_module.bake_control_rig_actions = _profiled_bake_control_rig_actions
    create_rig_module.anim_utils.bake_action = _profiled_blender_bake_action
    create_rig_module.correct_baked_ik_target_actions = _profiled_correct_baked_ik_target_actions
    create_rig_module.correct_baked_head_look_target_actions = _profiled_correct_baked_head_look_target_actions
    create_rig_module.set_control_rig_inverted = _profiled_set_control_rig_inverted

    _original_importer_bake = importer_module.bake_imported_actions_to_control_rig
    importer_module.bake_imported_actions_to_control_rig = _bake_actions

    bpy.utils.register_class(NWO_OT_BakeActiveAnimationToControlRig)

    action_menu = getattr(bpy.types, "DOPESHEET_MT_action", None)
    if action_menu is not None:
        action_menu.append(_draw_action_menu)
        _menu_types.append(action_menu)

    _original_draw_animation_manager = NWO_FoundryPanelProps.draw_animation_manager
    NWO_FoundryPanelProps.draw_animation_manager = _draw_animation_manager


def unregister():
    global _original_to_blender
    global _original_events_to_blender
    global _original_generate_renames
    global _original_importer_bake
    global _original_importer_init
    global _original_draw_animation_manager
    global _original_bake_control_rig_actions
    global _original_blender_bake_action
    global _original_correct_baked_ik_target_actions
    global _original_correct_baked_head_look_target_actions
    global _original_set_control_rig_inverted

    if _original_draw_animation_manager is not None:
        NWO_FoundryPanelProps.draw_animation_manager = _original_draw_animation_manager
        _original_draw_animation_manager = None

    for menu_type in _menu_types:
        try:
            menu_type.remove(_draw_action_menu)
        except Exception:
            pass
    _menu_types.clear()

    try:
        bpy.utils.unregister_class(NWO_OT_BakeActiveAnimationToControlRig)
    except RuntimeError:
        pass

    if _original_importer_bake is not None:
        importer_module.bake_imported_actions_to_control_rig = _original_importer_bake
        _original_importer_bake = None

    if _original_bake_control_rig_actions is not None:
        create_rig_module.bake_control_rig_actions = _original_bake_control_rig_actions
        create_rig_module.anim_utils.bake_action = _original_blender_bake_action
        create_rig_module.correct_baked_ik_target_actions = _original_correct_baked_ik_target_actions
        create_rig_module.correct_baked_head_look_target_actions = _original_correct_baked_head_look_target_actions
        create_rig_module.set_control_rig_inverted = _original_set_control_rig_inverted
        _original_bake_control_rig_actions = None
        _original_blender_bake_action = None
        _original_correct_baked_ik_target_actions = None
        _original_correct_baked_head_look_target_actions = None
        _original_set_control_rig_inverted = None

    if _original_to_blender is not None:
        animation_module.AnimationTag.to_blender = _original_to_blender
        animation_module.AnimationTag.events_to_blender = _original_events_to_blender
        animation_module.AnimationTag.generate_renames = _original_generate_renames
        _original_to_blender = None
        _original_events_to_blender = None
        _original_generate_renames = None

    if _original_importer_init is not None:
        importer_module.NWOImporter.__init__ = _original_importer_init
        _original_importer_init = None

    for cls, annotation in _original_bake_annotations:
        cls.__annotations__["graph_bake_to_control_rig"] = annotation
    _original_bake_annotations.clear()

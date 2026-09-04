from pathlib import Path
from time import perf_counter

import bpy

from . import foundry_output, perf_patch
from . import preferences as preferences_module
from .tools import importer as importer_module


_WM_VERBOSE_PROP = "foundry_fast_live_verbose_import_output"

_original_import_render_model = None
_original_import_object = None
_original_import_models = None
_original_import_animation_graph = None
_original_finish_bake = None
_original_live_verbose = None
_original_preferences_draw = None
_base_preferences_draw = None
_original_viewer_path = None


def _deferred_rigs(importer):
    rigs = getattr(importer, "_foundry_fast_deferred_control_rigs", None)
    if rigs is None:
        rigs = []
        importer._foundry_fast_deferred_control_rigs = rigs
    return rigs


def _remember_deferred_rig(importer, armature):
    if armature is None or armature.type != "ARMATURE":
        return
    rigs = _deferred_rigs(importer)
    if armature not in rigs:
        rigs.append(armature)


def _build_deferred_rig(importer, armature):
    if armature is None or armature.name not in bpy.data.objects:
        return False

    rigs = _deferred_rigs(importer)
    if armature not in rigs:
        return False

    animation_data = armature.animation_data
    original_action = animation_data.action if animation_data is not None else None
    original_slot = getattr(animation_data, "last_slot_identifier", "") if animation_data is not None else ""
    original_pose_position = armature.data.pose_position

    started = perf_counter()
    try:
        armature.data.pose_position = "REST"
        if animation_data is not None:
            animation_data.action = None
        importer.context.view_layer.update()
        importer.build_imported_control_rig(armature)
    finally:
        try:
            rigs.remove(armature)
        except ValueError:
            pass
        if animation_data is not None:
            if original_slot:
                try:
                    animation_data.last_slot_identifier = original_slot
                except (AttributeError, TypeError, ValueError):
                    pass
            animation_data.action = original_action
        armature.data.pose_position = original_pose_position
        importer.context.view_layer.update()

    print(f"[Foundry perf] Deferred control rig build: {perf_counter() - started:.3f}s ({armature.name})")
    return True


def _flush_deferred_rigs(importer):
    count = 0
    for armature in list(_deferred_rigs(importer)):
        count += int(_build_deferred_rig(importer, armature))
    return count


def _import_render_model(self, *args, **kwargs):
    allow_control_rig = kwargs.get("allow_control_rig", True)
    should_defer = bool(
        allow_control_rig
        and self.build_control_rig
        and getattr(self, "_foundry_fast_defer_control_rig", False)
    )
    if not should_defer:
        return _original_import_render_model(self, *args, **kwargs)

    original_build_control_rig = self.build_control_rig
    self.build_control_rig = False
    try:
        result = _original_import_render_model(self, *args, **kwargs)
    finally:
        self.build_control_rig = original_build_control_rig

    if isinstance(result, tuple) and len(result) > 1:
        _remember_deferred_rig(self, result[1])
    return result


def _import_object(self, *args, **kwargs):
    return_cin_stuff = bool(kwargs.get("return_cin_stuff", False))
    should_defer = bool(self.build_control_rig and (self.tag_animation or return_cin_stuff))
    previous = getattr(self, "_foundry_fast_defer_control_rig", False)
    self._foundry_fast_defer_control_rig = previous or should_defer
    try:
        result = _original_import_object(self, *args, **kwargs)
    finally:
        self._foundry_fast_defer_control_rig = previous

    if should_defer and not return_cin_stuff:
        _flush_deferred_rigs(self)
    return result


def _import_models(self, *args, **kwargs):
    should_defer = bool(self.build_control_rig and self.tag_animation)
    previous = getattr(self, "_foundry_fast_defer_control_rig", False)
    self._foundry_fast_defer_control_rig = previous or should_defer
    try:
        result = _original_import_models(self, *args, **kwargs)
    finally:
        self._foundry_fast_defer_control_rig = previous

    if should_defer:
        _flush_deferred_rigs(self)
    return result


def _import_animation_graph(self, file, armature, render, *args, **kwargs):
    result = _original_import_animation_graph(self, file, armature, render, *args, **kwargs)
    _build_deferred_rig(self, armature)
    return result


def _finish_bake(self):
    _flush_deferred_rigs(self)
    return _original_finish_bake(self)


def _live_verbose_enabled():
    try:
        return bool(getattr(bpy.context.window_manager, _WM_VERBOSE_PROP, False))
    except Exception:
        return False


def _find_base_preferences_draw():
    preferences_class = preferences_module.FoundryPreferences
    for owner, name, original in getattr(perf_patch, "_originals", ()):
        if owner is preferences_class and name == "draw":
            return original
    return preferences_class.draw


def _draw_preferences(self, context):
    _base_preferences_draw(self, context)
    box = self.layout.box()
    box.label(text="Performance")
    box.prop(context.window_manager, _WM_VERBOSE_PROP, text="Live Per-Item Import Output")
    row = box.row(align=True)
    row.operator("nwo.show_foundry_output", text="Show Foundry Output")
    row.operator("nwo.open_foundry_detail_log", text="Open Detailed Import Log")


def register():
    global _original_import_render_model
    global _original_import_object
    global _original_import_models
    global _original_import_animation_graph
    global _original_finish_bake
    global _original_live_verbose
    global _original_preferences_draw
    global _base_preferences_draw
    global _original_viewer_path

    _original_viewer_path = foundry_output._VIEWER_PATH
    foundry_output._VIEWER_PATH = Path(__file__).with_name("foundry_output_viewer_fast.pyw")

    setattr(
        bpy.types.WindowManager,
        _WM_VERBOSE_PROP,
        bpy.props.BoolProperty(
            name="Live Per-Item Import Output",
            description="Show detailed per-item import messages live. The full detail log is always saved",
            default=False,
        ),
    )

    _original_live_verbose = foundry_output._live_verbose_enabled
    foundry_output._live_verbose_enabled = _live_verbose_enabled

    _original_preferences_draw = preferences_module.FoundryPreferences.draw
    _base_preferences_draw = _find_base_preferences_draw()
    preferences_module.FoundryPreferences.draw = _draw_preferences

    _original_import_render_model = importer_module.NWOImporter.import_render_model
    _original_import_object = importer_module.NWOImporter.import_object
    _original_import_models = importer_module.NWOImporter.import_models
    _original_import_animation_graph = importer_module.NWOImporter.import_animation_graph
    _original_finish_bake = importer_module.NWOImporter.bake_imported_control_rig_actions

    importer_module.NWOImporter.import_render_model = _import_render_model
    importer_module.NWOImporter.import_object = _import_object
    importer_module.NWOImporter.import_models = _import_models
    importer_module.NWOImporter.import_animation_graph = _import_animation_graph
    importer_module.NWOImporter.bake_imported_control_rig_actions = _finish_bake


def unregister():
    global _original_viewer_path

    if _original_import_render_model is not None:
        importer_module.NWOImporter.import_render_model = _original_import_render_model
        importer_module.NWOImporter.import_object = _original_import_object
        importer_module.NWOImporter.import_models = _original_import_models
        importer_module.NWOImporter.import_animation_graph = _original_import_animation_graph
        importer_module.NWOImporter.bake_imported_control_rig_actions = _original_finish_bake

    if _original_preferences_draw is not None:
        preferences_module.FoundryPreferences.draw = _original_preferences_draw

    if _original_live_verbose is not None:
        foundry_output._live_verbose_enabled = _original_live_verbose

    if _original_viewer_path is not None:
        foundry_output._VIEWER_PATH = _original_viewer_path
        _original_viewer_path = None

    try:
        delattr(bpy.types.WindowManager, _WM_VERBOSE_PROP)
    except (AttributeError, RuntimeError):
        pass

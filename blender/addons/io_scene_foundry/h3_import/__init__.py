"""Experimental H3 source-object import. Reach remains the active project."""
from pathlib import Path
import os
import subprocess
import tempfile
import time
import traceback
import bpy
from bpy.props import BoolProperty, StringProperty
from bpy_extras.io_utils import ImportHelper
from .. import utils
from .core import find_tags_root, load_payload
from .builder import BuildSession

_active = []


class NWO_OT_ImportHalo3Object(bpy.types.Operator, ImportHelper):
    bl_idname = "nwo.import_halo3_object"
    bl_label = "Import Halo 3 Object (Experimental)"
    bl_description = "Read H3EK object dependencies into the current Reach project without changing source tags"
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = ""
    filter_glob: StringProperty(default="*.model;*.render_model;*.scenery;*.crate;*.biped;*.vehicle;*.weapon;*.device_machine;*.device_control;*.equipment;*.h3asset.json", options={'HIDDEN'})
    tags_root: StringProperty(name="Halo 3 Tags Directory", subtype='DIR_PATH', description="Source H3EK tags directory. Detected from the selected file when blank")
    helper_path: StringProperty(name="Extraction Helper", subtype='FILE_PATH', description="Optional override for h3-object-bridge.exe. The H3 test build includes a helper")
    import_collision: BoolProperty(name="Collision Geometry", default=True)
    import_physics: BoolProperty(name="Physics Reference Shapes", default=True, description="Excluded reference shapes, not a conversion of rigid-body simulation settings")
    reference_only: BoolProperty(name="Reference Only", default=True, description="Exclude the imported root collection from Foundry export until inspected")

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT' and utils.current_project_valid()
                and not utils.is_corinth(context) and not utils.get_scene_props().export_in_progress
                and not _active)

    def draw(self, context):
        layout = self.layout
        layout.label(text="H3EK source tags, not .map files")
        layout.prop(self, "tags_root")
        layout.prop(self, "helper_path")
        layout.prop(self, "import_collision")
        layout.prop(self, "import_physics")
        layout.prop(self, "reference_only")
        layout.label(text="Materials: placeholders with source references")
        layout.label(text="Animation import is not included in this pass")

    def execute(self, context):
        self._process = None
        self._log = None
        self._timer = None
        self._session = None
        self._steps = None
        self._cancel_requested = False
        self._started = time.monotonic()
        self._scene = context.scene
        self._view_layer = context.view_layer
        self._area = context.area
        self._selected = list(context.selected_objects)
        self._active_object = context.view_layer.objects.active
        self._settings = utils.get_scene_props()
        self._previous_busy = self._settings.export_in_progress
        self._phase = "Reading source"
        self._finished = False
        try:
            source = Path(bpy.path.abspath(self.filepath)).resolve(strict=True)
            if source.name.lower().endswith('.h3asset.json'):
                self._payload_path = source
            else:
                root = (Path(bpy.path.abspath(self.tags_root)).resolve(strict=True)
                        if self.tags_root else find_tags_root(source))
                if not root.is_dir() or not source.is_relative_to(root):
                    raise ValueError("Selected tag is outside the Halo 3 tags directory")
                destination = Path(utils.get_tags_path()).resolve()
                if root == destination:
                    raise ValueError("Halo 3 source tags and the active Reach tags directory must be different")
                helper = (Path(bpy.path.abspath(self.helper_path)) if self.helper_path else
                          Path(__file__).parent / "bin" / ("h3-object-bridge.exe" if os.name == 'nt' else "h3-object-bridge"))
                if not helper.is_file():
                    raise FileNotFoundError("H3 extraction helper not found. Install the H3 test artifact or set Extraction Helper")
                output = Path(tempfile.mkdtemp(prefix="foundry_h3_"))
                self._payload_path = output / "asset.h3asset.json"
                self._log_path = output / "helper.log"
                self._log = self._log_path.open('w', encoding='utf-8')
                command = [str(helper.resolve()), '--tags-root', str(root), '--input', str(source), '--output', str(output)]
                if self.import_collision:
                    command.append('--collision')
                if self.import_physics:
                    command.append('--physics')
                self._process = subprocess.Popen(command, stdout=self._log, stderr=subprocess.STDOUT,
                    cwd=str(output), creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self._settings.export_in_progress = True
            self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
            _active.append(self)
            context.window_manager.modal_handler_add(self)
            print("Halo 3 object import started. Source tags are read-only.")
            return {'RUNNING_MODAL'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            traceback.print_exc()
            self._finish(context, rollback=True)
            return {'CANCELLED'}

    def modal(self, context, event):
        if event.type == 'ESC' and not self._cancel_requested:
            self._cancel_requested = True
            self._cancel_at = time.monotonic()
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        try:
            if context.scene != self._scene or context.view_layer != self._view_layer:
                raise RuntimeError("Scene or view layer changed during H3 import")
            elapsed = time.monotonic() - self._started
            spinner = ('/', '-', '\\', '|')[int(elapsed * 8) % 4]
            if self._area is not None:
                self._area.header_text_set(f"( {spinner} ) H3 object: {self._phase} | {elapsed:.1f}s | Esc: cancel")
            if self._cancel_requested:
                if self._process is not None and self._process.poll() is None:
                    if time.monotonic() - self._cancel_at > 3:
                        self._process.kill()
                    return {'RUNNING_MODAL'}
                self._finish(context, rollback=True)
                return {'CANCELLED'}
            if self._process is not None:
                code = self._process.poll()
                if code is None:
                    return {'RUNNING_MODAL'}
                self._log.close()
                self._log = None
                text = self._log_path.read_text(encoding='utf-8', errors='replace')
                print(text)
                self._process = None
                if code != 0:
                    raise RuntimeError(f"H3 helper failed ({code}). {text[-1200:]}")
            if self._steps is None:
                payload = load_payload(self._payload_path)
                if not self.import_collision:
                    payload['collision'] = None
                if not self.import_physics:
                    payload['physics'] = None
                self._session = BuildSession(context, payload, self._payload_path, self.reference_only)
                self._steps = iter(self._session.build())
            deadline = time.monotonic() + 0.025
            while time.monotonic() < deadline:
                try:
                    self._phase = next(self._steps)
                except StopIteration:
                    self._finish(context)
                    print(f"[Foundry perf] Halo 3 object import: {elapsed:.3f}s")
                    self.report({'INFO'}, "H3 import complete. See the H3 import report in Blender's Text Editor")
                    return {'FINISHED'}
            return {'RUNNING_MODAL'}
        except Exception as exc:
            traceback.print_exc()
            self.report({'ERROR'}, str(exc))
            self._finish(context, rollback=True)
            return {'CANCELLED'}

    def _finish(self, context, rollback=False):
        if self._finished:
            return
        self._finished = True
        try:
            if self._process is not None and self._process.poll() is None:
                self._process.kill()
                self._process.wait(timeout=3)
            if self._steps is not None:
                self._steps.close()
            if rollback and self._session is not None:
                self._session.rollback()
            if rollback:
                for ob in context.selected_objects:
                    ob.select_set(False)
                for ob in self._selected:
                    try:
                        ob.select_set(True)
                    except ReferenceError:
                        pass
                try:
                    self._view_layer.objects.active = self._active_object
                except ReferenceError:
                    pass
        finally:
            if self._log is not None:
                self._log.close()
            if self._timer is not None:
                context.window_manager.event_timer_remove(self._timer)
            if self._area is not None:
                try:
                    self._area.header_text_set(None)
                except ReferenceError:
                    pass
            self._settings.export_in_progress = self._previous_busy
            if self in _active:
                _active.remove(self)


def menu_import(self, context):
    self.layout.operator(NWO_OT_ImportHalo3Object.bl_idname, text="Halo 3 Object (Foundry Experimental)")


def register():
    bpy.utils.register_class(NWO_OT_ImportHalo3Object)
    bpy.types.TOPBAR_MT_file_import.append(menu_import)


def unregister():
    for operator in list(_active):
        operator._finish(bpy.context, rollback=True)
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    bpy.utils.unregister_class(NWO_OT_ImportHalo3Object)

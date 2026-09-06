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
from .core import find_tags_root, resolve_tags_root, load_payload
from .builder import BuildSession
from .import_output import HelperLogTail, ImportProgress, open_output

_active = []


def _bundled_helper_path():
    filename = "h3-object-bridge.exe" if os.name == 'nt' else "h3-object-bridge"
    return Path(__file__).parent / "bin" / filename


def _source_paths(source):
    """Resolve source settings without loading an H3 project or changing Reach."""
    prefs = utils.get_prefs()
    configured_root = prefs.h3_tags_root.strip()
    configured = bpy.path.abspath(configured_root) if configured_root else None
    root = resolve_tags_root(source, configured)
    if configured and root != Path(configured).resolve():
        print(f'H3 source root normalized to tags directory: {root}', flush=True)
    if root == Path(utils.get_tags_path()).resolve():
        raise ValueError("Halo 3 source tags and the active Reach tags directory must be different")
    override = prefs.h3_extraction_helper.strip()
    helper = Path(bpy.path.abspath(override)) if override else _bundled_helper_path()
    if not helper.is_file():
        raise FileNotFoundError(
            "H3 extraction helper not found. Install the H3 test build or set "
            "Extraction Helper Override in Foundry preferences > Halo 3 Import"
        )
    return root, helper.resolve()


class NWO_OT_ImportHalo3Object(bpy.types.Operator, ImportHelper):
    bl_idname = "nwo.import_halo3_object"
    bl_label = "Import Halo 3 Asset (Experimental)"
    bl_description = "Read H3EK object or scenario dependencies into the current Reach project without changing source tags"
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = ""
    filter_glob: StringProperty(default="*.scenario;*.model;*.render_model;*.scenery;*.crate;*.biped;*.vehicle;*.weapon;*.device_machine;*.device_control;*.equipment;*.h3asset.json", options={'HIDDEN'})
    import_collision: BoolProperty(name="Collision Geometry", default=True)
    import_physics: BoolProperty(name="Physics Reference Shapes", default=True, description="Excluded reference shapes, not a conversion of rigid-body simulation settings")
    preview_materials: BoolProperty(name="Material Previews", default=True, description="Extract shader metadata and packed textures; no Reach tags are generated")
    flip_normal_green: BoolProperty(name="Flip Normal Green", default=True, description="Invert the green channel in preview nodes only; extracted pixels stay unchanged")
    reference_only: BoolProperty(name="Reference Only", default=True, description="Exclude the imported root collection from Foundry export until inspected")

    scenario_geometry: BoolProperty(name="BSP Geometry", default=True, description="Decode BSP geometry and placements as excluded references")
    scenario_hints: BoolProperty(name="Giant Sector and Rail Hints", default=True)
    scenario_objects: BoolProperty(name="Placed Game Objects", default=True, description="Reuse H3 object geometry by source tag and variant; excluded from export")
    scenario_content: BoolProperty(name="Scenario Content and AI Organization", default=True, description="Show authored positions and preserve source folders, squads, zones and objectives")
    scenario_points: BoolProperty(name="AI and Script Points", default=True, description="Show source-world firing positions and script points; unresolved reference frames remain in the report")
    scenario_bsp_indices: StringProperty(name="BSP Indices", default="", description="Comma-separated source BSP indices. Blank imports every BSP, not an inferred zone set")

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT' and utils.current_project_valid()
                and not utils.is_corinth(context) and not utils.get_scene_props().export_in_progress
                and not _active)

    def draw(self, context):
        layout = self.layout
        layout.label(text="H3EK source tags, not .map files")
        prefs = utils.get_prefs()
        layout.label(text="Paths: Foundry Preferences > Halo 3 Import")
        layout.label(text="H3 tags: " + ("Saved preference" if prefs.h3_tags_root.strip() else "Auto-detect"))
        layout.label(text="Helper: " + ("Preference override" if prefs.h3_extraction_helper.strip() else "Bundled"))
        if Path(getattr(self, 'filepath', '')).suffix.lower() == '.scenario':
            layout.prop(self, "scenario_geometry")
            layout.prop(self, "scenario_bsp_indices")
            layout.prop(self, "scenario_hints")
            layout.prop(self, "scenario_objects")
            layout.prop(self, "scenario_content")
            layout.prop(self, "scenario_points")
            layout.prop(self, "preview_materials")
            row = layout.row()
            row.enabled = self.preview_materials
            row.prop(self, "flip_normal_green")
            layout.label(text="Scenario reference only. No Reach tags are generated.")
            return
        layout.prop(self, "import_collision")
        layout.prop(self, "import_physics")
        layout.prop(self, "reference_only")
        layout.prop(self, "preview_materials")
        row = layout.row()
        row.enabled = self.preview_materials
        row.prop(self, "flip_normal_green")
        layout.label(text="Materials: Blender previews, not Reach shader tags")
        layout.label(text="Animation import is not included in this pass")

    def invoke(self, context, event):
        if not self.filepath:
            configured_root = utils.get_prefs().h3_tags_root.strip()
            if configured_root:
                root = Path(bpy.path.abspath(configured_root))
                if root.is_dir():
                    self.filepath = str(root.resolve()) + os.sep
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        self._process = None
        self._output = HelperLogTail()
        self._progress = None
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
        self._shader_started = False
        self._source_root = None
        self._is_scenario = False
        try:
            open_output(utils, bpy)
            self._progress = ImportProgress('asset', self._area)
            self._progress.update(self._phase, force=True)
            source = Path(bpy.path.abspath(self.filepath)).resolve(strict=True)
            self._is_scenario = source.suffix.lower() == '.scenario'
            self._source_tag = None
            if source.name.lower().endswith('.h3asset.json'):
                self._payload_path = source
            else:
                root, helper = _source_paths(source)
                self._source_root = root
                self._object_helper = helper
                self._source_tag = source.relative_to(root).as_posix()
                if self._is_scenario:
                    from .scenario_scene import bsp_selection
                    bsp_selection(self.scenario_bsp_indices)
                    helper = helper.with_name('h3-scenario-inspect.exe' if os.name == 'nt' else 'h3-scenario-inspect')
                    if not helper.is_file():
                        raise FileNotFoundError("Scenario inspector is missing beside the H3 extraction helper. Install the scenario prototype build.")
                temporary = Path(tempfile.mkdtemp(prefix="foundry_h3_"))
                output = temporary / "source" if self._is_scenario else temporary
                if self._is_scenario:
                    output.mkdir()
                self._payload_path = output / ("scene.h3scene.json" if self._is_scenario else "asset.h3asset.json")
                self._log_path = temporary / "helper.log"
                self._log = self._log_path.open('w', encoding='utf-8')
                self._output.follow(self._log_path)
                command = [str(helper.resolve()), '--tags-root', str(root), '--input', str(source), '--output', str(output)]
                if self._is_scenario:
                    if self.scenario_geometry:
                        command.append('--geometry')
                    if self.scenario_bsp_indices.strip():
                        command += ['--bsp-indices', self.scenario_bsp_indices]
                else:
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
            print("Halo 3 asset import started. Source tags are read-only.")
            return {'RUNNING_MODAL'}
        except KeyboardInterrupt:
            self._finish(context, rollback=True)
            return {'CANCELLED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            traceback.print_exc()
            self._finish(context, rollback=True, state='failed')
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
                self._area.header_text_set(f"( {spinner} ) H3 asset: {self._phase} | {elapsed:.1f}s | Esc: cancel")
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
                    self._output.poll()
                    self._progress.update(self._phase)
                    return {'RUNNING_MODAL'}
                self._log.close()
                self._log = None
                text = self._output.poll(final=True)
                self._process = None
                if code != 0:
                    if self._shader_started:
                        utils.print_warning(f"H3 shader extraction failed ({code}); geometry retained. {text[-1200:]}")
                    else:
                        raise RuntimeError(f"H3 helper failed ({code}). {text[-1200:]}")
            if self.preview_materials and not self._shader_started:
                self._shader_started = True
                if self._start_shader_helper():
                    return {'RUNNING_MODAL'}
            if self._steps is None:
                if self._is_scenario:
                    from .scenario_scene import load_scene
                    from .scenario_builder import ScenarioBuildSession
                    from .materials import load_manifest
                    self._progress.update('Validating scenario inventory', force=True)
                    payload, inventory = load_scene(self._payload_path, self._source_tag, progress=self._progress.update)
                    from .scenario_scene import result_messages
                    for message in result_messages(payload):
                        print(message, flush=True)
                    material_manifest = None
                    if self.preview_materials:
                        try:
                            material_manifest = load_manifest(self._payload_path.parent / 'shader_manifest.json', payload['source_tag'])
                        except (OSError, ValueError, TypeError) as error:
                            utils.print_warning(f"Scenario material metadata unavailable: {error}")
                    self._session = ScenarioBuildSession(context, payload, inventory, self._payload_path.parent,
                        material_manifest, self.scenario_hints, self.scenario_points, self.flip_normal_green,
                        import_objects=self.scenario_objects, import_content=self.scenario_content,
                        tags_root=self._source_root, object_helper=self._object_helper,
                        preview_materials=self.preview_materials)
                    self._steps = iter(self._session.steps())
                else:
                    self._progress.update('Validating object geometry', force=True)
                    payload = load_payload(self._payload_path)
                    if not self.import_collision:
                        payload['collision'] = None
                    if not self.import_physics:
                        payload['physics'] = None
                    self._session = BuildSession(context, payload, self._payload_path, self.reference_only,
                        self.preview_materials, self.flip_normal_green)
                    self._steps = iter(self._session.build())
            deadline = time.monotonic() + 0.025
            while time.monotonic() < deadline:
                try:
                    self._phase = next(self._steps)
                    self._progress.update(self._phase)
                except StopIteration:
                    self._finish(context)
                    print(f"[Foundry perf] Halo 3 asset import: {elapsed:.3f}s")
                    self.report({'INFO'}, "H3 import complete. See the H3 import report in Blender's Text Editor")
                    return {'FINISHED'}
            return {'RUNNING_MODAL'}
        except KeyboardInterrupt:
            self._finish(context, rollback=True)
            return {'CANCELLED'}
        except Exception as exc:
            traceback.print_exc()
            self.report({'ERROR'}, str(exc))
            self._finish(context, rollback=True, state='failed')
            return {'CANCELLED'}

    def _start_shader_helper(self):
        # Existing extractions can reuse their sidecar without starting a reader.
        output = self._payload_path.parent
        if (output / "shader_manifest.json").is_file() or self._source_root is None:
            return False
        helper = Path(__file__).parent / "bin" / ("h3-shader-bridge.exe" if os.name == 'nt' else "h3-shader-bridge")
        if not helper.is_file():
            utils.print_warning("H3 shader helper is missing; geometry will use placeholder materials")
            return False
        self._phase = "Reading shaders and bitmaps"
        self._log_path = output / 'shader-helper.log'
        self._log = self._log_path.open('w', encoding='utf-8')
        self._output.follow(self._log_path)
        command = [str(helper.resolve()), '--tags-root', str(self._source_root),
                   '--asset', str(self._payload_path), '--output', str(output)]
        reach = Path(utils.get_tags_path())
        if reach.is_dir():
            command.extend(['--reach-tags-root', str(reach.resolve())])
        try:
            self._process = subprocess.Popen(command, stdout=self._log, stderr=subprocess.STDOUT,
                cwd=str(output), creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except OSError as exc:
            self._log.close()
            self._log = None
            utils.print_warning(f"H3 shader helper could not start: {exc}; geometry retained")
            return False
        return True

    def _finish(self, context, rollback=False, state=None):
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
            if self._progress is not None:
                self._progress.finish(state or ('cancelled' if rollback else 'completed'))
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
    self.layout.operator(NWO_OT_ImportHalo3Object.bl_idname, text="Halo 3 Asset (Foundry Experimental)")


def register():
    from . import reach_ops
    reach_ops.register()
    bpy.utils.register_class(NWO_OT_ImportHalo3Object)
    bpy.types.TOPBAR_MT_file_import.append(menu_import)


def unregister():
    from . import reach_ops
    reach_ops.unregister()
    for operator in list(_active):
        operator._finish(bpy.context, rollback=True)
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    bpy.utils.unregister_class(NWO_OT_ImportHalo3Object)

"""Modal H3 animation extraction and isolated armature staging."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import traceback
import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper
from .. import utils
from .animations import load_manifest
from .animation_builder import AnimationStager, find_armature

_active = []


class NWO_OT_ImportH3Animations(bpy.types.Operator, ImportHelper):
    bl_idname = 'nwo.import_halo3_animations'
    bl_label = 'Import Halo 3 Animations (Experimental)'
    bl_description = 'Read H3 base animations onto a copy of the selected armature; preserve source rig and write no tags'
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = ''
    filter_glob: StringProperty(default='*.model;*.model_animation_graph;*.giant;*.scenery;*.crate;*.biped;*.vehicle;*.weapon;*.device_machine;*.device_control;*.equipment;*.h3anim.json', options={'HIDDEN'})
    animation_name: StringProperty(name='Exact Animation Name', default='combat:move_front',
        description='Exact source graph name, including colons. Blank imports all supported base clips')

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT' and find_armature(context) is not None
                and utils.current_project_valid() and not utils.is_corinth(context)
                and not utils.get_scene_props().export_in_progress and not _active)

    def draw(self, context):
        self.layout.prop(self, 'animation_name')
        self.layout.label(text='Select the H3 .model for complete rest transforms')
        self.layout.label(text='Target: copy of selected armature and bound objects')
        self.layout.label(text='Base clips only; overlays and events retain metadata')
        self.layout.label(text='H3 paths: Foundry Preferences > Halo 3 Import')

    def invoke(self, context, event):
        self._target = find_armature(context)
        if not self.filepath:
            configured = utils.get_prefs().h3_tags_root.strip()
            if configured:
                self.filepath = bpy.path.abspath(configured) + os.sep
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        self._process = self._log = self._timer = self._stager = self._steps = None
        self._finished = False
        self._cancel_at = None
        self._started = time.monotonic()
        self._scene, self._layer, self._area = context.scene, context.view_layer, context.area
        self._selected, self._old_active = list(context.selected_objects), context.view_layer.objects.active
        self._settings = utils.get_scene_props()
        self._previous_busy = self._settings.export_in_progress
        self._scene_state = (context.scene.frame_current, context.scene.frame_start, context.scene.frame_end,
                             context.scene.render.fps, context.scene.render.fps_base)
        self._phase = 'Reading source animation resources'
        try:
            self._target = getattr(self, '_target', None) or find_armature(context)
            if self._target is None:
                raise ValueError('Select the H3 or Reach armature before importing animations')
            source = Path(bpy.path.abspath(self.filepath)).resolve(strict=True)
            if source.name.endswith('.h3anim.json'):
                self._manifest = source
            else:
                from . import _source_paths
                root, _ = _source_paths(source)
                helper = Path(__file__).parent / 'bin' / ('h3-animation-bridge.exe' if os.name == 'nt' else 'h3-animation-bridge')
                if not helper.is_file():
                    raise FileNotFoundError('H3 animation helper missing. Install the animation test build')
                temp = Path(tempfile.mkdtemp(prefix='foundry_h3_animation_'))
                output = temp / 'extraction'
                output.mkdir()
                self._manifest = output / 'animations.h3anim.json'
                self._log_path = temp / 'animation-helper.log'
                self._log = self._log_path.open('w', encoding='utf-8')
                command = [str(helper.resolve()), '--tags-root', str(root), '--input', str(source), '--output', str(output)]
                if self.animation_name.strip():
                    command += ['--animation', self.animation_name.strip()]
                self._process = subprocess.Popen(command, cwd=str(temp), stdout=self._log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self._settings.export_in_progress = True
            self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
            _active.append(self)
            context.window_manager.modal_handler_add(self)
            print('[Foundry] H3 animation extraction started. Source tags are read-only.')
            return {'RUNNING_MODAL'}
        except Exception as exc:
            traceback.print_exc()
            self.report({'ERROR'}, str(exc))
            self._finish(context, rollback=True)
            return {'CANCELLED'}

    def modal(self, context, event):
        if event.type == 'ESC' and self._cancel_at is None:
            self._cancel_at = time.monotonic()
            if self._process and self._process.poll() is None:
                self._process.terminate()
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        try:
            if context.scene != self._scene or context.view_layer != self._layer:
                raise RuntimeError('Scene or view layer changed during animation import')
            elapsed = time.monotonic() - self._started
            if self._area:
                spinner = ('/', '-', '\\', '|')[int(elapsed * 8) % 4]
                self._area.header_text_set(f'({spinner}) H3 animation: {self._phase} | {elapsed:.1f}s | Esc: cancel')
            if self._cancel_at is not None:
                if self._process and self._process.poll() is None:
                    if time.monotonic() - self._cancel_at > 3:
                        self._process.kill()
                    return {'RUNNING_MODAL'}
                self._finish(context, rollback=True)
                return {'CANCELLED'}
            if self._process:
                code = self._process.poll()
                if code is None:
                    return {'RUNNING_MODAL'}
                self._log.close()
                self._log = None
                log = self._log_path.read_text(encoding='utf-8', errors='replace')
                print(log)
                self._process = None
                if code != 0:
                    raise RuntimeError(f'H3 animation helper failed ({code}): {log[-1600:]}')
            if self._steps is None:
                manifest = load_manifest(self._manifest)
                self._stager = AnimationStager(context, manifest, self._manifest.parent, self._target)
                self._steps = iter(self._stager.build())
            try:
                self._phase = next(self._steps)
            except StopIteration:
                count = len(self._stager.animations)
                self._finish(context)
                print(f'[Foundry perf] H3 animation staging: {count} clips, {elapsed:.3f}s')
                self.report({'INFO'}, f'{count} base animations staged on a copy. No Reach tags written')
                return {'FINISHED'}
        except Exception as exc:
            traceback.print_exc()
            self.report({'ERROR'}, str(exc))
            self._finish(context, rollback=True)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def _finish(self, context, rollback=False):
        if self._finished:
            return
        self._finished = True
        try:
            if self._process and self._process.poll() is None:
                self._process.kill()
                self._process.wait(timeout=3)
            if self._steps:
                self._steps.close()
            if rollback and self._stager:
                self._stager.rollback()
            if rollback:
                frame, start, end, fps, base = self._scene_state
                self._scene.frame_start, self._scene.frame_end = start, end
                self._scene.render.fps, self._scene.render.fps_base = fps, base
                self._scene.frame_set(frame)
                for ob in context.selected_objects:
                    ob.select_set(False)
                for ob in self._selected:
                    if ob.name in bpy.data.objects:
                        ob.select_set(True)
                if self._old_active and self._old_active.name in bpy.data.objects:
                    self._layer.objects.active = self._old_active
        finally:
            if self._log:
                self._log.close()
            if self._timer:
                context.window_manager.event_timer_remove(self._timer)
            if self._area:
                try:
                    self._area.header_text_set(None)
                except ReferenceError:
                    pass
            self._settings.export_in_progress = self._previous_busy
            if self in _active:
                _active.remove(self)


def menu_import(self, context):
    self.layout.operator(NWO_OT_ImportH3Animations.bl_idname, text='Halo 3 Animations (Foundry Experimental)')


def register():
    bpy.utils.register_class(NWO_OT_ImportH3Animations)
    bpy.types.TOPBAR_MT_file_import.append(menu_import)


def unregister():
    for op in list(_active):
        op._finish(bpy.context, rollback=True)
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    bpy.utils.unregister_class(NWO_OT_ImportH3Animations)

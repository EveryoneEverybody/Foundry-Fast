"""Modal H3 animation import with optional isolated staging."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import traceback
import bpy
from bpy.props import BoolProperty, StringProperty
from bpy_extras.io_utils import ImportHelper
from .. import utils
from .animations import load_manifest, selected_manifest
from .animation_builder import AnimationStager, find_armature
from .animation_append import AnimationAppender
from .import_output import HelperLogTail, ImportProgress, open_output

_active = []


class NWO_OT_ImportH3Animations(bpy.types.Operator, ImportHelper):
    bl_idname = 'nwo.import_halo3_animations'
    bl_label = 'Import Halo 3 Animations (Experimental)'
    bl_description = 'Add H3 actions to an existing armature, or optionally create a staging copy; write no tags'
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = ''
    # Blender's extension matcher truncates individual patterns to 15 characters.
    filter_glob: StringProperty(default='*.model;*.model*graph;*.giant;*.scenery;*.crate;*.biped;*.vehicle;*.weapon;*.device*;*.equipment;*.h3anim.json', options={'HIDDEN'})
    target_armature: StringProperty(name='Target Armature', options={'SKIP_SAVE'})
    create_staging_copy: BoolProperty(name='Create Staging Copy', default=False, options={'SKIP_SAVE'},
        description='Duplicate the target rig and its bound objects for isolated playback; otherwise add actions to the existing rig')
    include_overlays: BoolProperty(name='Import Time Overlays', default=False,
        description='Import local time overlays as composed JMO actions with a leading reference; independent from aim-screen samples')
    include_blend_screens: BoolProperty(name='Import Aim/Blend-Screen Poses', default=False,
        description='Import regular H3 aim-screen samples with stepped keys and retained screen metadata; no runtime aiming controller')
    animation_name: StringProperty(name='Exact Animation Name', default='combat:move_front',
        description='Exact source graph name, including colons. Blank imports all supported clips enabled below')

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT' and utils.current_project_valid() and not utils.is_corinth(context)
                and not utils.get_scene_props().export_in_progress and not _active)

    def draw(self, context):
        self.layout.prop_search(self, 'target_armature', context.scene, 'objects', text='Armature')
        self.layout.prop(self, 'create_staging_copy')
        self.layout.prop(self, 'animation_name')
        self.layout.prop(self, 'include_overlays')
        self.layout.prop(self, 'include_blend_screens')
        self.layout.label(text='Copy rig and meshes' if self.create_staging_copy else 'Actions only; no duplicate meshes')
        self.layout.label(text='H3 .model: preferred rest-pose source')
        self.layout.label(text='.model_animation_graph also accepted')
        self.layout.label(text='Base clips and enabled overlays; no tag writes')
        if not self.target_armature:
            self.layout.label(text='Choose an imported armature above', icon='INFO')

    def invoke(self, context, event):
        selected = find_armature(context)
        self.target_armature = selected.name if selected else ''
        if not self.filepath:
            configured = utils.get_prefs().h3_tags_root.strip()
            if configured:
                self.filepath = bpy.path.abspath(configured) + os.sep
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        self._process = self._log = self._timer = self._stager = self._steps = None
        self._finished = False
        self._output = HelperLogTail()
        self._progress = None
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
            open_output(utils, bpy)
            self._progress = ImportProgress('animation', self._area)
            self._progress.update(self._phase, force=True)
            self._target = (context.scene.objects.get(self.target_armature)
                            if self.target_armature else find_armature(context))
            if self._target is None or self._target.type != 'ARMATURE':
                raise ValueError('Choose a target armature. This command imports actions, not mesh geometry')
            if not self.poll(context):
                raise ValueError('Animation import requires an idle Reach project in Object Mode')
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
                self._output.follow(self._log_path)
                command = [str(helper.resolve()), '--tags-root', str(root), '--input', str(source), '--output', str(output)]
                if self.animation_name.strip():
                    command += ['--animation', self.animation_name.strip()]
                if self.include_overlays:
                    command.append('--include-overlays')
                if self.include_blend_screens:
                    command.append('--include-blend-screens')
                self._process = subprocess.Popen(command, cwd=str(temp), stdout=self._log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self._settings.export_in_progress = True
            self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
            _active.append(self)
            context.window_manager.modal_handler_add(self)
            print('[Foundry] H3 animation extraction started. Source tags are read-only.')
            return {'RUNNING_MODAL'}
        except KeyboardInterrupt:
            self._finish(context, rollback=True)
            return {'CANCELLED'}
        except Exception as exc:
            traceback.print_exc()
            self.report({'ERROR'}, str(exc))
            self._finish(context, rollback=True, state='failed')
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
                    self._output.poll()
                    self._progress.update(self._phase)
                    return {'RUNNING_MODAL'}
                self._log.close()
                self._log = None
                log = self._output.poll(final=True)
                self._process = None
                if code != 0:
                    raise RuntimeError(f'H3 animation helper failed ({code}): {log[-1600:]}')
            if self._steps is None:
                self._progress.update('Validating animation data', force=True)
                manifest = selected_manifest(load_manifest(self._manifest),
                                             self.include_overlays, self.include_blend_screens)
                builder = AnimationStager if self.create_staging_copy else AnimationAppender
                self._stager = builder(context, manifest, self._manifest.parent, self._target)
                self._steps = iter(self._stager.build())
            try:
                self._phase = next(self._steps)
                self._progress.update(self._phase)
            except StopIteration:
                count = len(self._stager.animations)
                self._finish(context)
                print(f'[Foundry perf] H3 animation staging: {count} clips, {elapsed:.3f}s')
                target = 'a staging copy' if self.create_staging_copy else self._target.name
                self.report({'INFO'}, f'{count} animations added to {target}. No Reach tags written')
                return {'FINISHED'}
        except KeyboardInterrupt:
            self._finish(context, rollback=True)
            return {'CANCELLED'}
        except Exception as exc:
            traceback.print_exc()
            self.report({'ERROR'}, str(exc))
            self._finish(context, rollback=True, state='failed')
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def _finish(self, context, rollback=False, state=None):
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
            if self._progress is not None:
                self._progress.finish(state or ('cancelled' if rollback else 'completed'))
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

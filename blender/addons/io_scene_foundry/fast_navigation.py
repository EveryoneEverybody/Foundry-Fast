import math
from time import perf_counter

import blf
import bpy
from mathutils import Matrix, Vector


_last_speed = None
_keymaps = []


def _clamp(value, low, high):
    return max(low, min(high, value))


class NWO_OT_FoundryFastNavigation(bpy.types.Operator):
    bl_idname = "nwo.foundry_fast_navigation"
    bl_label = "Foundry Fast Navigation"
    bl_description = "Sapien-style free navigation with a switchable orbit mode"
    bl_options = {"REGISTER"}

    sensitivity: bpy.props.FloatProperty(
        name="Mouse Sensitivity",
        default=0.0025,
        min=0.0001,
        max=0.02,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == "VIEW_3D"
            and context.region is not None
            and context.region.type == "WINDOW"
            and context.space_data is not None
            and context.space_data.type == "VIEW_3D"
        )

    def invoke(self, context, event):
        global _last_speed

        self._area = context.area
        self._region = context.region
        self._rv3d = context.space_data.region_3d
        self._window = context.window
        self._timer = None
        self._draw_handle = None
        self._keys = set()
        self._mode = "FREE"
        self._mouse_locked = True
        self._free_distance = 1.0
        self._last_tick = perf_counter()

        self._rv3d.view_perspective = "PERSP"
        self._eye = self._rv3d.view_matrix.inverted().translation.copy()
        self._pivot = self._rv3d.view_location.copy()
        self._distance = max((self._eye - self._pivot).length, 0.001)

        if _last_speed is None:
            self._speed = _clamp(max(self._rv3d.view_distance * 0.25, 1.0), 0.05, 1000.0)
        else:
            self._speed = _last_speed

        self._set_angles_from_forward(self._rv3d.view_rotation @ Vector((0.0, 0.0, -1.0)))
        self._apply_free_view()

        self._timer = context.window_manager.event_timer_add(1.0 / 60.0, window=context.window)
        self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_hud,
            (),
            "WINDOW",
            "POST_PIXEL",
        )
        context.window_manager.modal_handler_add(self)
        self._set_mouse_locked(True)
        self._warp_cursor()
        self._tag_redraw()
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        global _last_speed

        if event.type == "ESC" and event.value == "PRESS":
            _last_speed = self._speed
            self._finish(context)
            return {"FINISHED"}

        if event.type == "RIGHTMOUSE":
            if event.value == "PRESS":
                self._set_mouse_locked(not self._mouse_locked)
                self._keys.clear()
                if self._mouse_locked:
                    self._warp_cursor()
                self._tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type == "O" and event.value == "PRESS":
            self._toggle_mode(context)
            return {"RUNNING_MODAL"}

        if event.type == "F" and event.value == "PRESS":
            self._focus_selected(context)
            return {"RUNNING_MODAL"}

        if event.type in {
            "W", "A", "S", "D", "Q", "E",
            "LEFT_SHIFT", "RIGHT_SHIFT",
            "LEFT_CTRL", "RIGHT_CTRL",
        }:
            if event.value == "PRESS":
                self._keys.add(event.type)
            elif event.value == "RELEASE":
                self._keys.discard(event.type)
            return {"RUNNING_MODAL"}

        if event.type == "WHEELUPMOUSE" and event.value == "PRESS":
            if self._mode == "FREE":
                self._speed = _clamp(self._speed * 1.35, 0.01, 1000000.0)
                _last_speed = self._speed
            else:
                self._distance = max(self._distance / 1.25, 0.001)
                self._apply_orbit_view()
            self._tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type == "WHEELDOWNMOUSE" and event.value == "PRESS":
            if self._mode == "FREE":
                self._speed = _clamp(self._speed / 1.35, 0.01, 1000000.0)
                _last_speed = self._speed
            else:
                self._distance = min(self._distance * 1.25, 1000000000.0)
                self._apply_orbit_view()
            self._tag_redraw()
            return {"RUNNING_MODAL"}

        if self._mouse_locked and event.type == "MOUSEMOVE":
            center_x, center_y = self._cursor_center()
            dx = event.mouse_x - center_x
            dy = event.mouse_y - center_y
            if dx or dy:
                self._yaw += dx * self.sensitivity
                self._pitch = _clamp(
                    self._pitch + dy * self.sensitivity,
                    math.radians(-89.5),
                    math.radians(89.5),
                )
                if self._mode == "FREE":
                    self._apply_free_view()
                else:
                    self._apply_orbit_view()
                self._warp_cursor()
                self._tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type == "TIMER":
            self._tick()
            self._tag_redraw()
            return {"RUNNING_MODAL"}

        if not self._mouse_locked:
            return {"PASS_THROUGH"}

        return {"RUNNING_MODAL"}

    def cancel(self, context):
        self._finish(context)

    def _tick(self):
        now = perf_counter()
        dt = min(now - self._last_tick, 0.1)
        self._last_tick = now

        if not self._mouse_locked or not self._keys:
            return

        forward = self._forward()
        right = self._right()
        up = Vector((0.0, 0.0, 1.0))
        move = Vector((0.0, 0.0, 0.0))

        if "W" in self._keys:
            move += forward
        if "S" in self._keys:
            move -= forward
        if "D" in self._keys:
            move += right
        if "A" in self._keys:
            move -= right
        if "E" in self._keys:
            move += up
        if "Q" in self._keys:
            move -= up

        if move.length_squared == 0.0:
            return

        move.normalize()
        multiplier = 1.0
        if "LEFT_SHIFT" in self._keys or "RIGHT_SHIFT" in self._keys:
            multiplier *= 4.0
        if "LEFT_CTRL" in self._keys or "RIGHT_CTRL" in self._keys:
            multiplier *= 0.2

        delta = move * self._speed * multiplier * dt
        if self._mode == "FREE":
            self._eye += delta
            self._apply_free_view()
        else:
            self._pivot += delta
            self._apply_orbit_view()

    def _toggle_mode(self, context):
        if self._mode == "FREE":
            self._pivot = self._ray_target(context)
            to_pivot = self._pivot - self._eye
            if to_pivot.length_squared > 1e-12:
                self._distance = max(to_pivot.length, 0.001)
                self._set_angles_from_forward(to_pivot.normalized())
            self._mode = "ORBIT"
            self._apply_orbit_view()
        else:
            self._eye = self._current_eye()
            self._mode = "FREE"
            self._apply_free_view()
        self._warp_cursor()
        self._tag_redraw()

    def _focus_selected(self, context):
        target = self._selected_target(context)
        if target is None:
            return

        eye = self._current_eye()
        to_target = target - eye
        if to_target.length_squared <= 1e-12:
            return

        self._pivot = target
        self._distance = max(to_target.length, 0.001)
        self._set_angles_from_forward(to_target.normalized())
        self._mode = "ORBIT"
        self._apply_orbit_view()
        self._warp_cursor()
        self._tag_redraw()

    def _selected_target(self, context):
        obj = context.active_object
        if obj is None:
            return None

        if obj.type == "ARMATURE":
            if context.mode == "POSE" and context.active_pose_bone is not None:
                return obj.matrix_world @ context.active_pose_bone.head
            if context.mode == "EDIT_ARMATURE" and context.active_bone is not None:
                return obj.matrix_world @ context.active_bone.head

        if obj.select_get():
            return obj.matrix_world.translation.copy()
        return None

    def _ray_target(self, context):
        origin = self._current_eye()
        direction = self._forward()
        try:
            hit, location, _normal, _index, _object, _matrix = context.scene.ray_cast(
                context.evaluated_depsgraph_get(),
                origin,
                direction,
                distance=1000000000.0,
            )
            if hit:
                return location.copy()
        except Exception:
            pass
        return origin + direction * max(self._speed * 10.0, 10.0)

    def _set_angles_from_forward(self, forward):
        forward = forward.normalized()
        self._yaw = math.atan2(forward.x, forward.y)
        self._pitch = math.asin(_clamp(forward.z, -1.0, 1.0))

    def _rotation(self):
        forward = self._forward()
        right = forward.cross(Vector((0.0, 0.0, 1.0))).normalized()
        up = right.cross(forward).normalized()
        return Matrix((right, up, -forward)).transposed().to_quaternion()

    def _forward(self):
        cp = math.cos(self._pitch)
        return Vector((
            math.sin(self._yaw) * cp,
            math.cos(self._yaw) * cp,
            math.sin(self._pitch),
        )).normalized()

    def _right(self):
        return self._forward().cross(Vector((0.0, 0.0, 1.0))).normalized()

    def _current_eye(self):
        if self._mode == "FREE":
            return self._eye.copy()
        return self._pivot - self._forward() * self._distance

    def _apply_free_view(self):
        forward = self._forward()
        self._rv3d.view_rotation = self._rotation()
        self._rv3d.view_distance = self._free_distance
        self._rv3d.view_location = self._eye + forward * self._free_distance

    def _apply_orbit_view(self):
        self._rv3d.view_rotation = self._rotation()
        self._rv3d.view_location = self._pivot
        self._rv3d.view_distance = self._distance

    def _cursor_center(self):
        return (
            self._area.x + self._region.x + self._region.width // 2,
            self._area.y + self._region.y + self._region.height // 2,
        )

    def _warp_cursor(self):
        if not self._mouse_locked:
            return
        x, y = self._cursor_center()
        try:
            self._window.cursor_warp(x, y)
        except Exception:
            pass

    def _set_mouse_locked(self, locked):
        self._mouse_locked = locked
        try:
            if locked:
                self._window.cursor_modal_set("NONE")
            else:
                self._window.cursor_modal_restore()
        except Exception:
            pass

    def _draw_hud(self):
        try:
            if bpy.context.area != self._area:
                return
            eye = self._current_eye()
            font_id = 0
            blf.size(font_id, 14.0)
            blf.color(font_id, 0.85, 0.9, 0.85, 1.0)
            blf.position(font_id, 24, 54, 0)
            if self._mode == "FREE":
                status = f"Foundry Fast  FREE    Speed {self._speed:.2f}"
            else:
                status = f"Foundry Fast  ORBIT    Distance {self._distance:.2f}    Speed {self._speed:.2f}"
            blf.draw(font_id, status)

            blf.size(font_id, 12.0)
            blf.position(font_id, 24, 34, 0)
            blf.draw(
                font_id,
                "WASD move | Q/E vertical | Shift boost | Ctrl slow | Wheel speed/zoom | O mode | F selected | RMB mouse | Esc exit",
            )

            blf.position(font_id, 24, 16, 0)
            blf.draw(font_id, f"X {eye.x:.3f}    Y {eye.y:.3f}    Z {eye.z:.3f}")
        except Exception:
            pass

    def _tag_redraw(self):
        try:
            self._area.tag_redraw()
        except Exception:
            pass

    def _finish(self, context):
        self._keys.clear()
        self._set_mouse_locked(False)

        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None

        if self._draw_handle is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle, "WINDOW")
            except Exception:
                pass
            self._draw_handle = None

        self._tag_redraw()


def _draw_view_menu(self, context):
    self.layout.separator()
    self.layout.operator(
        NWO_OT_FoundryFastNavigation.bl_idname,
        text="Foundry Fast Navigation",
    )


def register():
    bpy.utils.register_class(NWO_OT_FoundryFastNavigation)
    bpy.types.VIEW3D_MT_view.append(_draw_view_menu)

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is not None:
        km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
        kmi = km.keymap_items.new(
            NWO_OT_FoundryFastNavigation.bl_idname,
            type="ACCENT_GRAVE",
            value="PRESS",
            shift=True,
            alt=True,
        )
        _keymaps.append((km, kmi))


def unregister():
    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)
    _keymaps.clear()

    try:
        bpy.types.VIEW3D_MT_view.remove(_draw_view_menu)
    except Exception:
        pass

    bpy.utils.unregister_class(NWO_OT_FoundryFastNavigation)

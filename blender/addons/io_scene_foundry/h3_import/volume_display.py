"""Foundry volume colors for H3 collision and physics reference meshes."""
import bpy
from .. import utils
from ..tools.materials import Collision, Physics


def volume_color(role):
    return tuple({'collision': Collision, 'physics': Physics}[role].color)


def configure_material(material, role):
    """Configure a newly created preview material, not a shared source material."""
    color = volume_color(role)
    material.diffuse_color = color
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    output = nodes.new('ShaderNodeOutputMaterial')
    material.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    bsdf.inputs['Base Color'].default_value = color
    bsdf.inputs['Alpha'].default_value = color[3]
    material.surface_render_method = 'BLENDED'
    material['h3_volume_preview'] = role


def configure_object(ob, role):
    ob.display_type = 'TEXTURED'
    ob.show_wire = False
    ob.show_transparent = True
    ob.color = volume_color(role)


def volume_role(ob):
    if ob.type != 'MESH':
        return None
    if ob.get('h3_physics_source'):
        return 'physics'
    if (getattr(ob.data.nwo, 'mesh_type', '') == '_connected_geometry_mesh_type_collision'
            and any(slot.material and slot.material.get('h3_source_object') for slot in ob.material_slots)):
        return 'collision'
    return None


def selected_volumes(context):
    selected = set(context.selected_objects)
    objects = set(selected)
    for collection in bpy.data.collections:
        if collection.get('h3_source_tag') or collection.get('h3_animation_source_graph'):
            members = set(collection.all_objects)
            if members & selected:
                objects.update(members)
    return [(ob, role) for ob in sorted(objects, key=lambda ob: ob.name)
            if (role := volume_role(ob)) is not None]


class VolumeDisplayUpdate:
    def __init__(self):
        self.created = []
        self.saved = []
        self.added_slots = []
        self.cache = {}

    def material(self, source, role):
        if source and source.get('h3_volume_preview') == role:
            return source
        key = (source.as_pointer() if source else None, role)
        if key not in self.cache:
            material = source.copy() if source else bpy.data.materials.new('H3 ' + role.title() + ' Reference')
            self.created.append(material)
            if source:
                material.name = source.name + ' volume preview'
            configure_material(material, role)
            self.cache[key] = material
        return self.cache[key]

    def apply(self, targets):
        # Validate all targets before changing any display state.
        for ob, role in targets:
            if ob.library or ob.data.library:
                raise ValueError('Volume display requires local editable objects')
            volume_color(role)
        for ob, role in targets:
            self.saved.append((ob, ob.display_type, ob.show_wire, ob.show_transparent,
                               tuple(ob.color), [(slot.link, slot.material) for slot in ob.material_slots]))
            if not ob.material_slots:
                ob.data.materials.append(None)
                self.added_slots.append(ob.data)
            for slot in ob.material_slots:
                preview = self.material(slot.material, role)
                slot.link = 'OBJECT'
                slot.material = preview
            configure_object(ob, role)
        return len(targets)

    def rollback(self):
        for ob, display, wire, transparent, color, slots in reversed(self.saved):
            ob.display_type, ob.show_wire, ob.show_transparent, ob.color = display, wire, transparent, color
            for slot, (link, material) in zip(ob.material_slots, slots):
                slot.link = link
                slot.material = material
        for mesh in reversed(self.added_slots):
            mesh.materials.pop(index=len(mesh.materials) - 1)
        for material in reversed(self.created):
            bpy.data.materials.remove(material, do_unlink=True)
        self.saved.clear()
        self.added_slots.clear()
        self.created.clear()
        self.cache.clear()


class NWO_OT_RefreshH3VolumeDisplay(bpy.types.Operator):
    bl_idname = 'nwo.refresh_h3_volume_display'
    bl_label = 'Refresh H3 Volume Display'
    bl_description = 'Use translucent Foundry collision and physics colors without reimporting geometry'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT' and bool(context.selected_objects)
                and not utils.get_scene_props().export_in_progress)

    def execute(self, context):
        update = VolumeDisplayUpdate()
        try:
            targets = selected_volumes(context)
            if not targets:
                self.report({'WARNING'}, 'Select an H3 import or one of its collision/physics reference meshes')
                return {'CANCELLED'}
            count = update.apply(targets)
            context.view_layer.update()
        except Exception as exc:
            update.rollback()
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, f'{count} H3 volumes updated. Geometry, names and export exclusions unchanged')
        return {'FINISHED'}


def register():
    bpy.utils.register_class(NWO_OT_RefreshH3VolumeDisplay)


def unregister():
    bpy.utils.unregister_class(NWO_OT_RefreshH3VolumeDisplay)

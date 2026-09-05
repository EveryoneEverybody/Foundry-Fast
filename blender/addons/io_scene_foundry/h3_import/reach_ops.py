"""Operators for staging and restoring H3 material assignments."""
import json
import bpy
from .. import utils
from .reach_builder import ReachStager


def import_objects(context):
    selected = set(context.selected_objects)
    result = set(selected)
    for collection in bpy.data.collections:
        if not collection.get('h3_shader_manifest'):
            continue
        members = set(collection.all_objects)
        if members & selected:
            result.update(members)
    return sorted(result, key=lambda ob: ob.name)


class NWO_OT_StageH3ReachMaterials(bpy.types.Operator):
    bl_idname = 'nwo.stage_h3_reach_materials'
    bl_label = 'Stage H3 Materials as Reach Nodes'
    bl_description = 'Create editable Foundry Reach materials for selected H3 imports; keep source previews and write no tags'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT' and bool(context.selected_objects)
                and utils.current_project_valid() and not utils.is_corinth(context)
                and not utils.get_scene_props().export_in_progress)

    def execute(self, context):
        stager = ReachStager()
        try:
            count = stager.apply(import_objects(context))
            report = bpy.data.texts.new('H3 Reach staging report')
            report.write(json.dumps({'format': 'foundry.h3-reach-staging', 'version': 1,
                                     'results': stager.results}, indent=2))
            context.view_layer.update()
        except Exception as exc:
            stager.rollback()
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        print(f'[Foundry] H3 Reach nodes: {count} materials staged. Report: {report.name}')
        self.report({'INFO'}, f'{count} Reach materials staged; no tags written. See {report.name}')
        return {'FINISHED'}


class NWO_OT_RestoreH3Materials(bpy.types.Operator):
    bl_idname = 'nwo.restore_h3_source_materials'
    bl_label = 'Restore H3 Source Materials'
    bl_description = 'Restore H3 preview materials on selected imports without deleting edited Reach materials'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_objects)

    def execute(self, context):
        count = 0
        for ob in import_objects(context):
            if ob.type != 'MESH' or ob.library:
                continue
            for index, slot in enumerate(ob.material_slots):
                material = slot.material
                if material is None or not material.get('h3_reach_staged'):
                    continue
                source = material.get('h3_source_material')
                if not isinstance(source, bpy.types.Material):
                    continue
                material.use_fake_user = True
                slot.material = source
                if index < len(ob.data.materials) and ob.data.materials[index] == source:
                    slot.link = 'DATA'
                count += 1
        context.view_layer.update()
        self.report({'INFO'}, f'{count} source material slots restored; staged Reach materials retained')
        return {'FINISHED'}


CLASSES = (NWO_OT_StageH3ReachMaterials, NWO_OT_RestoreH3Materials)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

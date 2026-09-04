import bpy

from . import utils
from .tools import clear_duplicate_materials as duplicate_materials_module
from .tools import importer as importer_module


_original_module_function = None
_original_importer_function = None


def clear_duplicate_materials(strip_legacy_halo_naming: bool, materials_scope=None):
    materials = bpy.data.materials
    scope_set = None if materials_scope is None else set(materials_scope)
    basenames = set()
    to_remove = set()

    for mat in tuple(materials):
        if scope_set is not None and mat not in scope_set:
            continue

        base = utils.base_material_name(mat.name, strip_legacy_halo_naming)
        basenames.add(base)
        if base != mat.name:
            to_remove.add(mat)
        if not materials.get(base, 0):
            new_mat = mat.copy()
            new_mat.name = base
            if materials_scope is not None:
                materials_scope.append(new_mat)
                scope_set.add(new_mat)

    remap_targets = {
        mat: materials.get(utils.base_material_name(mat.name, strip_legacy_halo_naming))
        for mat in (tuple(materials) if scope_set is None else scope_set)
        if mat.name not in basenames
    }

    for ob in bpy.data.objects:
        for slot in ob.material_slots:
            mat = slot.material
            if mat in remap_targets:
                slot.material = remap_targets[mat]

    for mat in to_remove:
        materials.remove(mat)

    if scope_set is None:
        return [mat for mat in bpy.data.materials]
    return [mat for mat in bpy.data.materials if mat in scope_set]


def register():
    global _original_module_function, _original_importer_function
    if _original_module_function is not None:
        return

    _original_module_function = duplicate_materials_module.clear_duplicate_materials
    _original_importer_function = importer_module.clear_duplicate_materials
    duplicate_materials_module.clear_duplicate_materials = clear_duplicate_materials
    importer_module.clear_duplicate_materials = clear_duplicate_materials


def unregister():
    global _original_module_function, _original_importer_function
    if _original_module_function is None:
        return

    duplicate_materials_module.clear_duplicate_materials = _original_module_function
    importer_module.clear_duplicate_materials = _original_importer_function
    _original_module_function = None
    _original_importer_function = None

from pathlib import Path
import struct
import time
import bpy
from math import tau
from mathutils import Matrix, Quaternion, Vector
import numpy as np
import types

from ..constants import WU_SCALAR
from ..managed_blam.decorator_set import DecoratorSetTag
from ..managed_blam.scenario import ScenarioTag
from .. import utils

    
class NWO_OT_ExportDecorators(bpy.types.Operator):
    bl_idname = "nwo.export_airprobes"
    bl_label = "Export Airprobes"
    bl_description = "Exports all airprobes"
    bl_options = {"UNDO"}

    @classmethod
    def poll(cls, context):
        return utils.valid_nwo_asset(context) and not utils.is_corinth(context)

    def execute(self, context):
        current_selection = context.selected_objects[:]
        current_object = context.object
        export_airprobes()
        for ob in current_selection:
            ob.select_set(True)
        context.view_layer.objects.active = current_object
        return {"FINISHED"}

def gather_airprobes(context):
    print("--- Start airprobe gather")
    start = time.perf_counter()
    
    collection_map = utils.create_parent_mapping(context)
    proxies = []
    with utils.DepsgraphRead():
        depsgraph = context.evaluated_depsgraph_get()

        for inst in depsgraph.object_instances:
            obj = inst.object
            original = obj.original
            nwo = original.nwo
            parent = original
            
            if inst.is_instance:
                obj = inst.instance_object
                original = obj.original
                nwo = original.nwo
                parent = inst.parent
            
            if not (original.type == 'EMPTY' and nwo.marker_type != '_connected_geometry_marker_type_airprobe'):
                continue
            
            if utils.ignore_for_export_fast(original, collection_map, parent):
                continue

            proxy = types.SimpleNamespace()
            proxy.name = original.name
            proxy.type = 'EMPTY'
            proxy.nwo = nwo
            proxy.matrix_world = inst.matrix_world.copy()
            proxies.append(proxy)

    print(len(proxies), "airprobes found")
    print("--- Gathered airprobes in: {:.3f}s".format(time.perf_counter() - start))
        
    return proxies

def _placement_field_offsets(element):
    offsets = {}
    offset = 0
    for field in element.Fields:
        offsets[field.FieldName] = offset
        offset += int(field.Size)
        
    return offsets, offset

def _serialized_block_with_payload(template, count, payload):
    data = bytearray(template)
    lbgt = data.rfind(b"lbgt")
    dtpc = data.rfind(b"dtpc", 0, lbgt)
    if lbgt == -1 or dtpc == -1:
        raise ValueError("Serialized decorator placement block does not contain expected chunks")
    
    values_start = lbgt + 20
    data = data[:values_start] + payload + data[values_start:]
    struct.pack_into("<I", data, 8, len(data) - 12)
    struct.pack_into("<I", data, dtpc + 8, len(data) - dtpc - 12)
    struct.pack_into("<I", data, lbgt + 8, len(payload) + 8)
    struct.pack_into("<I", data, lbgt + 12, count)
    return bytes(data)

def _byte_value(value):
    return max(0, min(255, int(value)))

def _airprobe_byte_value(value):
    value = _byte_value(value)
    
    return value

def _airprobe_placement_dtype(offsets, element_size):
    fields = (
        ("airprobe_position", "airprobe position", ("<f4", (3,))),
        ("airprobe_name", "airprobe name", "u1"),
        ("manual_bsp_flags", "manual bsp flags", "u1"),
        ("manual_lighting", "manual lighting", "u1"),
    )
    missing = [field_name for _, field_name, _ in fields if field_name not in offsets]
    if missing:
        raise ValueError(f"Airprobe block is missing fields: {', '.join(missing)}")
    
    names = [name for name, _, _ in fields]
    formats = [fmt for _, _, fmt in fields]
    field_offsets = [offsets[field_name] for _, field_name, _ in fields]
    
    return np.dtype({
        "names": names,
        "formats": formats,
        "offsets": field_offsets,
        "itemsize": element_size,
    })

def _build_airprobe_placement_payload(airprobe_objects, offsets, element_size):
    payload = bytearray(element_size * len(airprobe_objects))
    if not airprobe_objects:
        return payload
    
    rows = np.ndarray(len(airprobe_objects), dtype=_airprobe_placement_dtype(offsets, element_size), buffer=payload)
    for idx, ob in enumerate(airprobe_objects):
        matrix = utils.halo_transforms_matrix(ob.matrix_world)
        rows["airprobe_position"][idx] = tuple(matrix.translation)
        rows["airprobe_name"] = utils.clean_text(ob.name)
        
    return payload

def _write_decorator_placements_serialized(placements, decorator_objects, decorator_types, corinth):
    placements.RemoveAllElements()
    if not decorator_objects:
        return
    
    template_element = placements.AddElement()
    offsets, element_size = _placement_field_offsets(template_element)
    placements.RemoveAllElements()
    
    payload = _build_decorator_placement_payload(decorator_objects, decorator_types, corinth, offsets, element_size)
    serialized = _serialized_block_with_payload(bytes(placements.Serialize()), len(decorator_objects), payload)
    placements.Deserialize(serialized)

def _write_decorator_placements_elementwise(placements, decorator_objects, decorator_types, corinth):
    placements.RemoveAllElements()
    type_indices = _decorator_type_indices(decorator_types)
    for ob in decorator_objects:
        placement = placements.AddElement()
        matrix = utils.halo_transforms_matrix(ob.matrix_world)
        placement.SelectField("position").Data = matrix.translation
        q = matrix.to_quaternion()
        placement.SelectField("rotation").Data = q[1], q[2], q[3], q[0]
        placement.SelectField("scale").Data = max(ob.matrix_world.to_scale().to_tuple())
        
        variant = ob.nwo.marker_game_instance_tag_variant_name.strip().lower()
        if variant:
            placement.SelectField("type index").Data = type_indices.get(variant, 0)
        
        motion_scale = int(ob.nwo.decorator_motion_scale * 255)
        ground_tint = int(ob.nwo.decorator_ground_tint * 255)
                
        if not corinth:
            motion_scale = utils.signed_int8(motion_scale)
            ground_tint = utils.signed_int8(ground_tint)
            
        placement.SelectField("motion scale").Data = motion_scale
        placement.SelectField("ground tint").Data = ground_tint
        
        placement.SelectField("tint color").Data = [utils.linear_to_srgb(c) for c in ob.nwo.decorator_tint]
        
        placement.SelectField("bsp index").Data = -1
        placement.SelectField("cluster index").Data = -1
        if corinth:
            placement.SelectField("cluster decorator set index").Data = -1
    
def export_decorators(corinth, decorator_objects = None):
    scenario_path = utils.get_asset_tag(".scenario", True)
    scene_nwo = utils.get_scene_props()
    if corinth and scene_nwo.decorators_from_blender_child_scenario.strip():
        scenario_path = str(Path(scenario_path).with_name(scene_nwo.decorators_from_blender_child_scenario).with_suffix(".scenario"))
    
    tags_dir = utils.get_tags_path()
    context = bpy.context
    if decorator_objects is None:
        decorator_objects = gather_decorators(context)
    
    decorator_sets = {}
    MAX_SETS = 48
    MAX_PLACEMENTS_PER_SET = 262_144
    for ob in decorator_objects:
        tag_path = utils.relative_path(ob.nwo.marker_game_instance_tag_name.lower())
        index = 0

        while True:
            values = decorator_sets.setdefault((tag_path, index), [])
            if len(values) < MAX_PLACEMENTS_PER_SET:
                values.append(ob)
                break
            index += 1

            if len(decorator_sets) > MAX_SETS:
                for k in list(decorator_sets.keys())[:-MAX_SETS]:
                    del decorator_sets[k]
                    
    print("--- Writing decorators to Tag")
    start = time.perf_counter()
    with ScenarioTag(path=scenario_path) as scenario:
        decorator_block = scenario.tag.SelectField("Block:decorators")
        if decorator_block.Elements.Count < 1:
            set_element = decorator_block.AddElement()
        else:
            set_element = decorator_block.Elements[0]
            
        sets_block = set_element.SelectField("Block:sets")
        sets_block.RemoveAllElements()
        # print("Max sets size", sets_block.MaximumElementCount)
        
        for key, value in decorator_sets.items():
            path = key[0]
            if path and Path(tags_dir, path).exists():
                with DecoratorSetTag(path=path) as decorator_set:
                    decorator_types = decorator_set.get_decorator_types()
                    decorator_path = decorator_set.tag_path
                element = sets_block.AddElement()
                element.SelectField("Reference:decorator set").Path = decorator_path
                placements = element.SelectField("Block:placements")
                # print("Max placements size", placements.MaximumElementCount)
                try:
                    _write_decorator_placements_serialized(placements, value, decorator_types, corinth)
                except Exception as error:
                    print(f"Serialized decorator write failed for {path}, using element writes: {error}")
                    _write_decorator_placements_elementwise(placements, value, decorator_types, corinth)
                
                    
        scenario.tag_has_changes = True
    print("--- Completed decorators tag write in", utils.human_time(time.perf_counter() - start, True))
                            
                    

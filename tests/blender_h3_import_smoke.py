"""Blender construction test with synthetic data and minimal Foundry property stubs.

This is not an H3EK import or a Reach export test.
"""
import copy
import importlib
import importlib.util
import math
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).parent))
from h3_import_fixture import payload

ROOT = Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry'
NAME = 'foundry_h3_smoke'
package = ModuleType(NAME)
package.__path__ = [str(ROOT)]
sys.modules[NAME] = package
settings = SimpleNamespace(scale='blender', forward_direction='x', maintain_marker_axis=True, export_in_progress=False)
utils = ModuleType(NAME + '.utils')
utils.get_scene_props = lambda: settings
utils.rotation_diff_from_forward = lambda start, end: math.pi / 2 if end == 'y' else 0.0
utils.set_region = lambda ob, name, mode: ob.__setitem__('test_region', name)
utils.set_permutation = lambda ob, name, mode: ob.__setitem__('test_permutation', name)
utils.SetType = SimpleNamespace(MODEL=1)
utils.print_warning = print
utils.current_project_valid = lambda: True
utils.is_corinth = lambda context: False
sys.modules[NAME + '.utils'] = utils
for part, path in [('managed_blam', ROOT / 'managed_blam'), ('h3_import', ROOT / 'h3_import')]:
    module = ModuleType(NAME + '.' + part)
    module.__path__ = [str(path)]
    sys.modules[module.__name__] = module

class TestMeshProps(bpy.types.PropertyGroup):
    mesh_type: bpy.props.StringProperty()

class TestObjectProps(bpy.types.PropertyGroup):
    def get_mesh_type(self):
        return self.id_data.data.nwo.mesh_type if self.id_data.type == 'MESH' else ''
    mesh_type: bpy.props.StringProperty(get=get_mesh_type)
    marker_type: bpy.props.StringProperty()
    node_order_source: bpy.props.StringProperty()

class TestCollectionProps(bpy.types.PropertyGroup):
    type: bpy.props.StringProperty()

for cls in (TestMeshProps, TestObjectProps, TestCollectionProps):
    bpy.utils.register_class(cls)
bpy.types.Mesh.nwo = bpy.props.PointerProperty(type=TestMeshProps)
bpy.types.Object.nwo = bpy.props.PointerProperty(type=TestObjectProps)
bpy.types.Collection.nwo = bpy.props.PointerProperty(type=TestCollectionProps)
core = importlib.import_module(NAME + '.h3_import.core')
BuildSession = importlib.import_module(NAME + '.h3_import.builder').BuildSession

def snapshot():
    return tuple(len(store) for store in [bpy.data.objects, bpy.data.meshes, bpy.data.armatures, bpy.data.materials, bpy.data.collections, bpy.data.texts])

def near(actual, expected):
    assert (Vector(actual) - Vector(expected)).length < 1e-4, (actual, expected)

for scale, forward in [('blender', 'x'), ('blender', 'y'), ('max', 'x')]:
    settings.scale, settings.forward_direction = scale, forward
    data = payload()
    data['collision'] = copy.deepcopy(data['render'])
    data['collision']['markers'] = []
    core.validate_payload(data)
    before = snapshot()
    session = BuildSession(bpy.context, data, 'synthetic.h3asset.json', True)
    stages = list(session.build())
    assert stages[-1] == 'Complete'
    root = next(c for c in bpy.data.collections if c.get('h3_source_tag') == data['source_tag'])
    assert root.nwo.type == 'exclude'
    armature = session.armature
    assert [b.name for b in armature.data.bones] == ['b_pedestal', 'b_panel']
    assert armature.data.bones['b_panel'].parent.name == 'b_pedestal'
    assert armature.nwo.node_order_source == ''
    near(armature.data.bones['b_panel'].head_local, session.position([150, 200, 0]))
    render = next(o for o in bpy.data.objects if o.name.startswith('render:'))
    assert render.data.nwo.mesh_type == '_connected_geometry_mesh_type_default'
    collision = next(o for o in bpy.data.objects if o.name.startswith('collision:'))
    assert collision.data.nwo.mesh_type == '_connected_geometry_mesh_type_collision'
    near(render.data.vertices[0].co, session.position([150, 200, 0]))
    assert len(render.data.uv_layers) == 1
    assert render.vertex_groups['b_panel'].weight(0) == 1
    assert len([m for m in bpy.data.materials if m.get('h3_source_object')]) == 4
    marker = next(o for o in bpy.data.objects if o.get('h3_source_marker') == 'attach')
    near(marker.matrix_world.translation, session.position([160, 200, 0]))
    physics = next(o for o in bpy.data.objects if o.get('h3_physics_source'))
    assert physics.parent_bone == 'b_panel'
    near(physics.matrix_world.translation, session.position([150, 200, 0]))
    assert next(c for c in physics.users_collection).nwo.type == 'exclude'
    if scale == 'blender' and forward == 'x':
        before_position = render.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices[0].co.copy()
        armature.pose.bones['b_panel'].location.z += 1
        bpy.context.view_layer.update()
        after_position = render.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices[0].co.copy()
        near(after_position - before_position, [0, 0, 1])
    session.rollback()
    assert snapshot() == before, (snapshot(), before)

# Registration checks the real import operator and its file-menu entry.
spec = importlib.util.spec_from_file_location(NAME + '.h3_import', ROOT / 'h3_import/__init__.py', submodule_search_locations=[str(ROOT / 'h3_import')])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.register()
assert hasattr(bpy.ops.nwo, 'import_halo3_object')
module.unregister()
print('H3 Blender smoke test passed: scale, rotation, skeleton, skinning, markers, material separation, physics references, rollback and operator registration')

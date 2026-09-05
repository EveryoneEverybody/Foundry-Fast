"""Test H3 helper display and target lookup without game assets."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from blender_h3_import_smoke import *
import json
import tempfile

D = importlib.import_module(NAME + '.h3_import.volume_display')
B = importlib.import_module(NAME + '.h3_import.animation_builder')
settings.scale, settings.forward_direction = 'blender', 'x'
data = payload()
data['render']['materials'][1]['label'] = '(2) default body'
data['collision'] = copy.deepcopy(data['render'])
data['collision']['markers'] = []
before = snapshot()
session = BuildSession(bpy.context, data, 'synthetic.h3asset.json', True)
list(session.build())
arm = session.armature
root = next(c for c in bpy.data.collections if c.get('h3_source_tag') == data['source_tag'])
collision = next(o for o in root.all_objects if D.volume_role(o) == 'collision')
physics = next(o for o in root.all_objects if D.volume_role(o) == 'physics')
render = next(o for o in root.all_objects if o.name.startswith('render:'))
marker = next(o for o in root.all_objects if o.get('h3_source_marker'))

for ob, role in ((collision, 'collision'), (physics, 'physics')):
    assert ob.display_type == 'TEXTURED' and ob.show_transparent and not ob.show_wire
    assert tuple(ob.color)[:3] == D.volume_color(role)[:3]
    assert abs(ob.color[3] - 0.2) < 1e-6
    assert ob.hide_render
    for slot in ob.material_slots:
        material = slot.material
        assert material.surface_render_method == 'BLENDED'
        assert material['h3_volume_preview'] == role
        bsdf = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        assert abs(bsdf.inputs['Alpha'].default_value - 0.2) < 1e-6
        assert tuple(bsdf.inputs['Base Color'].default_value)[:3] == D.volume_color(role)[:3]
assert collision.data.nwo.mesh_type == '_connected_geometry_mesh_type_collision'
assert physics.data.nwo.mesh_type != '_connected_geometry_mesh_type_physics'
assert all(c.nwo.type == 'exclude' for c in physics.users_collection)
assert len(collision.data.materials) == 2
assert collision.data.materials[0] != collision.data.materials[1]
assert [p.material_index for p in collision.data.polygons] == [0, 1]
assert {m['h3_source_label'] for m in collision.data.materials} == {'(1) default body', '(2) default body'}
assert all(not m.get('h3_volume_preview') for m in render.data.materials)

# Bone parenting and nested helpers resolve to the same armature as skinned meshes.
for ob in (arm, collision, physics, marker, render):
    assert B.find_armature(SimpleNamespace(object=ob)) == arm, ob.name
nested = session.object('nested helper', None, root)
nested.parent = physics
assert B.find_armature(SimpleNamespace(object=nested)) == arm
unrelated = session.object('unrelated', None, bpy.context.scene.collection)
assert B.find_armature(SimpleNamespace(object=unrelated)) is None
assert B.find_armature(SimpleNamespace(object=None)) is None

# Emulate an older import with source collision materials and no physics material.
legacy_materials = []
for i in range(2):
    material = session.remember(bpy.data.materials, bpy.data.materials.new(f'legacy source {i}'))
    material['h3_source_object'] = data['source_tag']
    material['h3_source_name'] = f'physical material {i}'
    material.diffuse_color = (1, 0.5, 0.25, 1)
    legacy_materials.append(material)
for i, material in enumerate(legacy_materials):
    collision.data.materials[i] = material
# A source material shared with render geometry must not be recolored.
render.data.materials[0] = legacy_materials[0]
physics.data.materials.clear()
for ob in (collision, physics):
    ob.display_type = 'WIRE'
    ob.show_wire = True
    ob.show_transparent = False

def geometry_state(ob):
    return (ob.data, tuple(tuple(v.co) for v in ob.data.vertices),
            tuple(tuple(p.vertices) for p in ob.data.polygons),
            tuple(p.material_index for p in ob.data.polygons), ob.name, ob.parent, ob.parent_bone,
            tuple(tuple(row) for row in ob.matrix_world), ob.hide_render,
            tuple((c.name, c.nwo.type) for c in ob.users_collection), ob.data.nwo.mesh_type)

original = {ob: geometry_state(ob) for ob in (collision, physics)}
physics_metadata = physics['h3_physics_source']
old_snapshot = snapshot()
update = D.VolumeDisplayUpdate()
assert update.apply([(collision, 'collision'), (physics, 'physics')]) == 2
assert geometry_state(collision) == original[collision]
assert geometry_state(physics) == original[physics]
assert physics['h3_physics_source'] == physics_metadata
assert tuple(collision.data.materials) == tuple(legacy_materials)
assert render.material_slots[0].material == legacy_materials[0]
assert tuple(legacy_materials[0].diffuse_color) == (1, 0.5, 0.25, 1)
assert collision.material_slots[0].link == 'OBJECT'
assert collision.material_slots[0].material != collision.material_slots[1].material
assert collision.material_slots[0].material['h3_source_name'] == 'physical material 0'
assert collision.material_slots[1].material['h3_source_name'] == 'physical material 1'
mat_count = len(bpy.data.materials)
second = D.VolumeDisplayUpdate()
second.apply([(collision, 'collision'), (physics, 'physics')])
assert len(bpy.data.materials) == mat_count
second.rollback()
update.rollback()
assert snapshot() == old_snapshot
assert tuple(collision.data.materials) == tuple(legacy_materials)
assert len(physics.material_slots) == 0
assert collision.display_type == 'WIRE' and collision.show_wire and not collision.show_transparent
assert all(slot.link == 'DATA' for slot in collision.material_slots)

# The refresh operator works on the selected import, not unrelated Reach objects.
D.register()
for ob in bpy.context.selected_objects:
    ob.select_set(False)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
assert bpy.ops.nwo.refresh_h3_volume_display() == {'FINISHED'}
assert unrelated.display_type == 'TEXTURED' and not unrelated.show_transparent
objects_before = len(bpy.data.objects)
assert bpy.ops.nwo.refresh_h3_volume_display() == {'FINISHED'}
assert len(bpy.data.objects) == objects_before
assert tuple(collision.data.materials) == tuple(legacy_materials)
D.unregister()

# Reopened data retains the display, source material slots and exclusions.
collision_name, physics_name = collision.name, physics.name
with tempfile.TemporaryDirectory() as directory:
    path = str(Path(directory) / 'volumes.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    collision, physics = bpy.data.objects[collision_name], bpy.data.objects[physics_name]
    assert collision.show_transparent and physics.show_transparent
    assert collision.material_slots[0].link == 'OBJECT'
    assert collision.material_slots[0].material['h3_source_name'] == 'physical material 0'
    assert collision.data.materials[0]['h3_source_name'] == 'physical material 0'
    assert all(c.nwo.type == 'exclude' for c in physics.users_collection)
    assert physics['h3_physics_source'] == physics_metadata
print('H3 volume tests passed: native colors/alpha, solid display, separate material identities, retained slots, geometry, names, exclusions, parent lookup, repeat refresh, rollback and reopen')

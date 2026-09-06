"""Static references retain evaluated properties, material links and split normals."""
from pathlib import Path
import sys
import tempfile
import math
import bpy
from mathutils import Quaternion
sys.path.insert(0, str(Path(__file__).parent))
import blender_scenario_reference_smoke as base

base.main = bpy.context.scene
base.material = bpy.data.materials['shared textured material']
reference = base.reference
importer = base.Importer(bpy.context)
session = reference.Session(importer, True)
main = bpy.context.scene
view_layer = bpy.context.view_layer


def driver(socket, target, path, expression='value'):
    curve = socket.driver_add('default_value')
    curve.driver.type = 'SCRIPTED'
    variable = curve.driver.variables.new()
    variable.name = 'value'
    variable.type = 'SINGLE_PROP'
    variable.targets[0].id = target
    variable.targets[0].data_path = path
    curve.driver.expression = expression
    return curve


with session.isolated():
    root = bpy.data.collections.new('material driver reference')
    bpy.context.scene.collection.children.link(root)
    objects, arm = importer.import_render_model('driver_fixture', root, None, set())
    mesh = next(ob for ob in objects if ob.type == 'MESH')
    arm['health'] = 0.25
    mesh['glow'] = 4.0
    curve = mesh.driver_add('["glow"]')
    curve.driver.type = 'SCRIPTED'
    variable = curve.driver.variables.new()
    variable.name = 'health'; variable.type = 'SINGLE_PROP'
    variable.targets[0].id = arm
    variable.targets[0].data_path = '["health"]'
    curve.driver.expression = 'health * 2'
    own_material = base.material.copy()
    mesh.material_slots[0].link = 'OBJECT'
    mesh.material_slots[0].material = own_material
    node = own_material.node_tree.nodes.new('ShaderNodeValue')
    node.name = 'evaluated glow'
    material_curve = driver(node.outputs[0], mesh, '["glow"]')
    arm.pose.bones['child'].rotation_mode = 'QUATERNION'
    arm.pose.bones['child'].rotation_quaternion = Quaternion((0, 0, 1), math.pi / 5)
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    evaluated = mesh.evaluated_get(dg)
    assert abs(evaluated['glow'] - 0.5) < 1e-6
    normal_matrix = evaluated.matrix_world.to_3x3().inverted().transposed()
    normals = [(normal_matrix @ normal.vector).normalized() for normal in evaluated.data.corner_normals]
    expected_positions = [(evaluated.matrix_world @ vertex.co).copy() for vertex in evaluated.data.vertices]
    source_name = mesh.name
    reference.freeze_collection(root, bpy.context, objects, importer)
    mesh = bpy.data.objects[source_name]
    bpy.context.view_layer.update()
    assert len(root.all_objects) == 1 and objects == [mesh]
    assert not mesh.animation_data and abs(mesh['glow'] - 0.5) < 1e-6
    assert mesh.material_slots[0].link == 'OBJECT'
    assert mesh.material_slots[0].material == own_material
    assert material_curve.driver.variables[0].targets[0].id == mesh
    actual_matrix = mesh.matrix_world.to_3x3().inverted().transposed()
    for actual, expected in zip(mesh.data.corner_normals, normals):
        assert ((actual_matrix @ actual.vector).normalized() - expected).length < 1e-5
    for actual, expected in zip(mesh.data.vertices, expected_positions):
        assert ((mesh.matrix_world @ actual.co) - expected).length < 1e-5
    bpy.context.scene.collection.children.unlink(root)
    main.collection.children.link(root)
assert bpy.context.scene == main and bpy.context.view_layer == view_layer

# A material dependency on a removed helper keeps the complete live hierarchy.
with session.isolated():
    root = bpy.data.collections.new('live material dependency')
    bpy.context.scene.collection.children.link(root)
    objects, arm = importer.import_render_model('live_fixture', root, None, set())
    mesh = next(ob for ob in objects if ob.type == 'MESH')
    own_material = base.material.copy()
    mesh.material_slots[0].link = 'OBJECT'; mesh.material_slots[0].material = own_material
    node = own_material.node_tree.nodes.new('ShaderNodeValue')
    arm['health'] = 1.0
    driver(node.outputs[0], arm, '["health"]')
    before = tuple(root.all_objects)
    try:
        reference.freeze_collection(root, bpy.context, objects, importer)
        raise AssertionError('Expected live material fallback')
    except ValueError as error:
        assert 'Material driver references' in str(error)
    assert tuple(root.all_objects) == before
    assert mesh.parent == arm and mesh.modifiers[0].object == arm
session.close()
assert bpy.context.scene == main and bpy.context.view_layer == view_layer
assert not reference._settings
print('Scenario reference driver checks passed: evaluated properties, object material slots, driver remapping, posed split normals, live dependency fallback and window restoration')

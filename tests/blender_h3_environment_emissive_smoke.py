"""Exercise the actual material Power RNA/export path without tag writes.

Blender --background --factory-startup --python this.py -- report.json deps-dir
"""
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import tempfile

repo = Path(__file__).resolve().parents[1]
args = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
temporary = tempfile.TemporaryDirectory(prefix='foundry-emissive-smoke-') if not args else None
output = Path(args[0]) if args else Path(temporary.name)/'material-power-rna.json'
assert not output.exists(), 'Use a new report path'
sys.path[:0] = [str(repo/'blender/addons'), *args[1:2]]
import bpy
bpy.ops.preferences.addon_enable(module='io_scene_foundry')
from io_scene_foundry import utils
from io_scene_foundry.export.virtual_geometry import gather_face_props, MeshType

mesh = bpy.data.meshes.new('Synthetic emissive material assignment')
mesh.from_pydata([(0,0,0),(1,0,0),(1,1,0),(0,1,0)], [], [(0,1,2),(0,2,3)])
material = bpy.data.materials.new('Synthetic fixture')
untouched = bpy.data.materials.new('Untouched surface')
mesh.materials.append(material); mesh.materials.append(untouched)
mesh.polygons[1].material_index = 1
prop = material.nwo.material_props.add(); prop.type = 'emissive'
prop.material_lighting_emissive_color = [utils.srgb_to_linear(v) for v in (.635294,.756863,.827451)]
prop.material_lighting_attenuation_falloff = 1/(100*.3280839895013123)
prop.material_lighting_attenuation_cutoff = 2/(100*.3280839895013123)
prop.material_lighting_emissive_per_unit = False
scene = SimpleNamespace(corinth=False, atten_scalar=100)
values = []
for power in (3.2, 25.):
    prop.material_lighting_emissive_power = power
    exported = gather_face_props(mesh.nwo, mesh, len(mesh.polygons), scene, None, {},
        {material: [0]}, {'bungie_mesh_type': MeshType.default.value}, False, [])
    values.append({k: v.array.tolist() for k,v in exported.items()})
assert values[0].keys() == values[1].keys()
for key in values[0]:
    if key == 'bungie_lighting_emissive_power':
        assert abs(values[0][key][0]-3.2)<1e-6 and values[1][key] == [25.,0.]
    else:
        assert values[0][key] == values[1][key], key
assert values[1]['bungie_lighting_attenuation_falloff'] == [1.,0.]
assert values[1]['bungie_lighting_attenuation_cutoff'] == [2.,0.]
output.write_text(json.dumps(dict(status='PASS', blender=bpy.app.version_string,
    source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    material_power_rna='material.nwo.material_props[emissive].material_lighting_emissive_power',
    baseline=values[0], power25=values[1], kit_writes=False, shader_nodes_modified=False), indent=2))
print('MATERIAL_POWER_EXPORT_PASS', output)

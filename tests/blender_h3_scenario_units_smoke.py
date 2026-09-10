"""Compare real construction paths; decoder JMS and ASS both use SCALE=100.

Pinned blam-tags 5d0509f: geometry.rs SCALE, jms.rs read_vertex/build_geometry,
ass.rs from_scenario_structure_bsp. No inferred character-height constant.
"""
import copy
import json
from pathlib import Path
import runpy
import tempfile
import bpy
from mathutils import Vector

base = runpy.run_path(str(Path(__file__).with_name('blender_h3_scenario_smoke.py')))
from h3_import_fixture import payload
from h3_scenario_fixture import write_bundle, instance

for units in ('blender', 'max'):
    for forward in ('x', 'y'):
        bpy.context.scene.nwo.scale = units
        bpy.context.scene.nwo.forward_direction = forward
        base['base']['settings'].scale = units
        base['base']['settings'].forward_direction = forward
        object_session = base['base']['BuildSession'](bpy.context, payload(), 'fixture.h3asset.json', True)
        expected = object_session.position([100., 200., 300.])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scene, inventory = write_bundle(root)
            # Put every category's first point at the same source-world coordinate.
            for row in inventory['records']:
                if row['type'] == 'real point 3d':
                    row['value']['values'] = [1., 2., 3.]
            original = copy.deepcopy(inventory)
            bsp_path = root / 'geometry/bsp_0000.json'
            bsp = json.loads(bsp_path.read_text())
            bsp['instances'] = [instance(0, 0, position=[100., 200., 300.])]
            bsp_path.write_text(json.dumps(bsp))
            session = base['mod'].ScenarioBuildSession(bpy.context, scene, inventory, root)
            list(session.steps())
            bpy.context.view_layer.update()
            mesh = next(o for o in session.root.all_objects if o.type == 'MESH')
            base['near'](mesh.matrix_world @ mesh.data.vertices[0].co, expected)
            for role in ('sectors', 'rails', 'firing_positions', 'script_points'):
                ob = next(o for o in session.root.all_objects if o.get('h3_source_role') == role)
                actual = ob.matrix_world @ Vector(ob.data.splines[0].points[0].co[:3]) if ob.type == 'CURVE' else ob.location
                base['near'](actual, expected)
                assert json.loads(ob['h3_source_hint'])['points'][0] == [1., 2., 3.]
            assert inventory == original
            retained = json.loads(bpy.data.texts[session.root['h3_scenario_manifest']].as_string())
            assert retained == original
            session.rollback()
print('H3 unit consistency passed: object/BSP geometry, firing positions, Giant sectors/rails, script points; both scale modes and forward axes')

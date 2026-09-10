import importlib.util
from pathlib import Path
import tempfile
import unittest
from h3_import_fixture import payload

MODULE = Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry/h3_import/core.py'
spec = importlib.util.spec_from_file_location('h3_core', MODULE)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


class CoreTests(unittest.TestCase):
    def test_valid(self):
        core.validate_payload(payload())

    def test_wrong_format(self):
        data = payload()
        data['version'] = 2
        with self.assertRaises(ValueError):
            core.validate_payload(data)

    def test_wrong_units(self):
        data = payload()
        data['units'] = 'meters'
        with self.assertRaises(ValueError):
            core.validate_payload(data)

    def test_wrong_game(self):
        data = payload()
        data['game'] = 'haloreach_mcc'
        with self.assertRaises(ValueError):
            core.validate_payload(data)

    def test_nonfinite(self):
        data = payload()
        data['render']['vertices'][0]['position'][0] = float('nan')
        with self.assertRaises(ValueError):
            core.validate_payload(data)

    def test_zero_quaternion(self):
        data = payload()
        data['render']['nodes'][0]['rotation'] = [0, 0, 0, 0]
        with self.assertRaises(ValueError):
            core.validate_payload(data)

    def test_cycle(self):
        data = payload()
        data['render']['nodes'][0]['parent'] = 1
        with self.assertRaises(ValueError):
            core.validate_payload(data)

    def test_duplicate_names(self):
        data = payload()
        data['render']['nodes'][1]['name'] = 'b_pedestal'
        with self.assertRaises(ValueError):
            core.validate_payload(data)

    def test_bone_name_truncation(self):
        data = payload()
        data['render']['nodes'][1]['name'] = 'x' * 64
        with self.assertRaises(ValueError):
            core.validate_payload(data)

    def test_negative_weight(self):
        data = payload()
        data['render']['vertices'][0]['weights'] = [[1, -1]]
        with self.assertRaises(ValueError):
            core.validate_payload(data)

    def test_invalid_weight_bone(self):
        data = payload()
        data['render']['vertices'][0]['weights'] = [[4, 1]]
        with self.assertRaises(ValueError):
            core.validate_payload(data)

    def test_invalid_material(self):
        data = payload()
        data['render']['triangles'][0]['material'] = 99
        with self.assertRaises(ValueError):
            core.validate_payload(data)

    def test_invalid_vertex(self):
        data = payload()
        data['render']['triangles'][0]['vertices'][0] = 99
        with self.assertRaises(ValueError):
            core.validate_payload(data)

    def test_degenerate_triangle(self):
        data = payload()
        data['render']['triangles'][0]['vertices'] = [0, 0, 1]
        with self.assertRaises(ValueError):
            core.validate_payload(data)

    def test_partition_labels(self):
        self.assertEqual(core.material_partition('(1) default body'), ('body', 'default', ''))
        self.assertEqual(core.material_partition('(1) superhigh default body'), ('body', 'default', 'superhigh'))
        with self.assertRaises(ValueError):
            core.material_partition('unexpected')

    def test_permutations_stay_separate(self):
        mesh = payload()['render']
        self.assertEqual(len(core.groups(mesh)), 2)

    def test_coincident_vertices_are_not_welded(self):
        mesh = payload()['render']
        vertices, faces = core.compact_mesh(mesh, mesh['triangles'])
        self.assertEqual(len(vertices), 4)
        self.assertEqual(vertices[0]['position'], vertices[3]['position'])
        self.assertNotEqual(faces[0][0], faces[1][0])

    def test_ambiguous_materials(self):
        data = payload()
        self.assertEqual(len(core.shader_candidates('metal', data['shader_paths'])), 2)
        self.assertEqual(core.shader_candidates('missing', data['shader_paths']), [])

    def test_collision_bone_ownership(self):
        mesh = payload()['render']
        self.assertEqual(next(iter(core.groups(mesh, collision=True)))[3], 1)
        mesh['vertices'][0]['weights'] = [[0, 1]]
        with self.assertRaises(ValueError):
            core.groups(mesh, collision=True)

    def test_source_root_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'tags/objects/test.scenery'
            path.parent.mkdir(parents=True)
            path.write_text('fixture')
            # The reader returns a canonical path, including Windows short-name expansion.
            self.assertEqual(core.find_tags_root(path), path.parents[1].resolve(strict=True))

    def test_instance_labels_stay_separate(self):
        data = payload()
        data['render']['materials'][0]['label'] = '(1) armor_left'
        data['render']['materials'][1]['label'] = '(2) armor_right'
        core.validate_payload(data)
        self.assertEqual(len(core.groups(data['render'])), 2)
        self.assertEqual(core.material_partition('(1) armor_left'), ('default', 'default', ''))

    def test_physics_uses_its_own_node_indices(self):
        data = payload()
        core.validate_payload(data)
        data['physics']['shapes'][0]['node'] = 1
        with self.assertRaises(ValueError):
            core.validate_payload(data)

    def test_physics_space(self):
        data = payload()
        data['physics']['shape_space'] = 'world'
        with self.assertRaises(ValueError):
            core.validate_payload(data)

    def test_physics_missing_bone(self):
        data = payload()
        data['physics']['nodes'][0]['name'] = 'missing'
        with self.assertRaises(ValueError):
            core.validate_payload(data)

    def test_invalid_physics(self):
        data = payload()
        data['physics']['shapes'][0]['size'] = [0, 1, 2]
        with self.assertRaises(ValueError):
            core.validate_payload(data)


if __name__ == '__main__':
    unittest.main()

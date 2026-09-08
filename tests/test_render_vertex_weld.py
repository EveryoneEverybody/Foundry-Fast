"""Render welding must preserve deformation, including the real Voi door seam."""
import importlib.util
import json
from pathlib import Path
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('vertex_weld', ROOT / 'blender/addons/io_scene_foundry/export/vertex_weld.py')
weld = importlib.util.module_from_spec(spec)
spec.loader.exec_module(weld)


class RenderVertexWeldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((ROOT / 'tests/fixtures/voi_door_render_skinning.json').read_text())
        rows = cls.fixture['corners']
        cls.positions = np.array([r['position'] for r in rows], dtype=np.float32)
        cls.normals = np.array([r['normal'] for r in rows], dtype=np.float32)
        cls.uvs = np.array([r['uv'] for r in rows], dtype=np.float32)
        cls.bones = np.array([r['bone_indices'] for r in rows], dtype=np.uint8)
        cls.weights = np.array([r['bone_weights'] for r in rows], dtype=np.uint8)

    def door_weld(self, skin=True):
        arrays = weld.render_weld_components(self.positions, self.normals, [self.uvs], None, None,
            self.bones if skin else None, self.weights if skin else None)
        return weld.stable_unique_rows_with_epsilon(arrays, 1e-4)

    def test_door_fixture_reproduces_exact_manual_failure_before_fix(self):
        first, inverse = self.door_weld(skin=False)
        changed = np.flatnonzero(np.any(self.bones != self.bones[first[inverse]], axis=1))
        rows = self.fixture['corners']
        self.assertEqual(len(changed), self.fixture['expected_legacy_wrong_corners'])
        self.assertEqual({rows[i]['bad_native_and_manual_vertex'] for i in changed},
                         set(self.fixture['manual_owner_change_vertices']))

    def test_door_keeps_every_source_corner_owner(self):
        first, inverse = self.door_weld()
        np.testing.assert_array_equal(self.bones[first[inverse]], self.bones)
        np.testing.assert_array_equal(self.weights[first[inverse]], self.weights)
        self.assertLess(len(first), len(self.positions))  # Still weld genuine duplicates.
        self.assertTrue(np.all(np.diff(first) > 0))

    def test_separating_door_halves_preserves_source_deformation(self):
        translations = np.zeros((len(self.fixture['bone_bindings']), 3))
        translations[0, 1] = 50
        translations[1, 1] = -50
        expected = self.positions + (translations[self.bones] * self.weights[:, :, None] / 255).sum(axis=1)
        first, inverse = self.door_weld()
        np.testing.assert_allclose(expected[first[inverse]], expected, atol=1e-4, rtol=0)
        old_first, old_inverse = self.door_weld(skin=False)
        self.assertGreater(np.max(np.abs(expected[old_first[old_inverse]] - expected)), 99)

    def test_distinct_blends_keep_weight_bytes_and_identical_blends_merge(self):
        positions = np.zeros((3, 3), dtype=np.float32)
        bones = np.array([[0, 1, 0, 0]] * 3, dtype=np.uint8)
        weights = np.array([[128, 127, 0, 0], [127, 128, 0, 0], [128, 127, 0, 0]], dtype=np.uint8)
        arrays = weld.render_weld_components(positions, None, None, None, None, bones, weights)
        first, inverse = weld.stable_unique_rows_with_epsilon(arrays, 1e-4)
        np.testing.assert_array_equal(first, [0, 1])
        np.testing.assert_array_equal(inverse, [0, 1, 0])
        np.testing.assert_array_equal(weights[first[inverse]], weights)
        self.assertTrue(np.all((weights > 0).sum(axis=1) == 2))

    def test_each_render_attribute_can_prevent_a_merge(self):
        positions = np.zeros((2, 3), dtype=np.float32)
        for attribute in ('normals', 'texcoords', 'lighting_texcoords', 'vertex_colors'):
            with self.subTest(attribute=attribute):
                arguments = dict(positions=positions, normals=None, texcoords=None,
                    lighting_texcoords=None, vertex_colors=None, bone_indices=None, bone_weights=None)
                values = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float32)
                arguments[attribute] = [values] if attribute in ('texcoords', 'vertex_colors') else values
                first, inverse = weld.stable_unique_rows_with_epsilon(weld.render_weld_components(**arguments), 1e-4)
                np.testing.assert_array_equal(first, [0, 1])
                np.testing.assert_array_equal(inverse, [0, 1])

    def test_unskinned_and_position_only_welding_keep_epsilon_and_stable_order(self):
        positions = np.array([[2, 0, 0], [0, 0, 0], [2.000001, 0, 0]], dtype=np.float32)
        for arrays in ([positions], weld.render_weld_components(positions, None, None, None, None, None, None)):
            first, inverse = weld.stable_unique_rows_with_epsilon(arrays, 1e-4)
            np.testing.assert_array_equal(first, [0, 1])
            np.testing.assert_array_equal(inverse, [0, 1, 0])


if __name__ == '__main__':
    unittest.main()

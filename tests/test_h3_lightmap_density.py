"""Exact material palettes; no rounding, class-default drift, or blind migration."""
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace, ModuleType
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry/h3_import'))
from port_environment.lightmap_density import (BUCKET_FIELDS, density_palette,
    source_density, native_density_issues, ignore_target_default)
from port_environment import native_scene


def material(value=None):
    return dict(properties=[] if value is None else [dict(type={'name': 'lightmap resolution'},
        **{'real-value': {'values': [value]}})])


class DensityTests(unittest.TestCase):
    def test_absent_property_is_one(self):
        self.assertEqual(source_density(material()), 1)

    def test_all_observed_fractional_and_integer_requests_round_trip(self):
        for value in [.001, .01, .010999956168234348, .012000001035630703,
                      .05, .1, .17299996316432953, .2, 1, 2, 3, 4]:
            with self.subTest(value=value):
                row = material(value); result = density_palette([row])
                self.assertEqual(result['bucket_values'][result['material_indices'][0]-1], source_density(row))

    def test_seven_values_preserved_without_integer_coercion(self):
        values = [1, .2, .01, 3, .001, .012, .011]
        result = density_palette([material(v) for v in values])
        self.assertEqual(len(set(result['bucket_values'])), 7)
        self.assertEqual([result['bucket_values'][i-1] for i in result['material_indices']],
                         [source_density(material(v)) for v in values])

    def test_palette_deterministic_for_different_material_orders(self):
        self.assertEqual(density_palette([material(.2), material(4)])['bucket_values'],
                         density_palette([material(4), material(.2)])['bucket_values'])

    def test_eighth_value_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'More than seven'):
            density_palette([material(x) for x in range(1, 9)])

    def test_nonfinite_negative_zero_and_clamped_density_rejected(self):
        for value in [float('nan'), float('inf'), -float('inf'), -1, 0, .00001, 1e100]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                source_density(material(value))

    def test_duplicate_property_rejected(self):
        row = material(1); row['properties'] *= 2
        with self.assertRaises(ValueError): source_density(row)

    def test_source_ir_unchanged(self):
        rows = [material(.2), material(4)]; before = deepcopy(rows)
        density_palette(rows)
        self.assertEqual(rows, before)

    def test_receiver_class_override(self):
        for name in ['shader', 'shader_terrain', 'shader_foliage']:
            self.assertTrue(ignore_target_default('example.' + name))
        with self.assertRaises(ValueError): ignore_target_default('example.unknown')

    def test_real_face_adapter_uses_paired_palette_and_override(self):
        package = ModuleType('io_scene_foundry'); package.utils = SimpleNamespace()
        constants = ModuleType('io_scene_foundry.constants'); constants.WU_SCALAR = 3.048
        captured = []
        with patch.dict(sys.modules, {'io_scene_foundry': package, 'io_scene_foundry.constants': constants}), \
             patch.object(native_scene, 'face_property', side_effect=lambda mesh, kind, values, selected: captured.append((kind, values, selected))):
            native_scene.render_properties(SimpleNamespace(data=object()), {'triangles': [{'material': 0}, {'material': 1}]}, [],
                [{'source_shader': 'a.shader'}, {'source_shader': 'b.shader_foliage'}], [material(.2), material()])
        self.assertEqual(captured[0][1], {'lightmap_resolution_scale': '2'})
        self.assertEqual(captured[1][1], {'lightmap_ignore_default_resolution_scale': True})
        self.assertEqual(captured[2][1], {'lightmap_resolution_scale': '1'})
        self.assertEqual(captured[3][1], {'lightmap_ignore_default_resolution_scale': True})

    def native_fixture(self, suffix='shader'):
        source = 'source.' + suffix; target = 'target.' + suffix
        return [material(.2)], [dict(source_shader=source)], {source: target}, [
            {'render method': target, 'lightmap resolution scale': 1.0, 'lightmap flags': 8}], [dict(zip(BUCKET_FIELDS, [1, 4, 16, 64, 128, 256, 512]))]

    def test_native_mismatch_is_actionable_and_read_only(self):
        args = self.native_fixture(); before = deepcopy(args)
        issues = native_density_issues(*args, bsp_index=6)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]['bsp_index'], 6)
        self.assertEqual(issues[0]['source_material_slot'], 0)
        self.assertEqual(issues[0]['native_candidates'][0]['density'], 1)
        self.assertEqual(args, before)

    def test_native_exact_palette_is_accepted(self):
        args = self.native_fixture(); args[4][0][BUCKET_FIELDS[0]] = source_density(args[0][0])
        self.assertEqual(native_density_issues(*args), [])

    def test_native_foliage_requires_class_override(self):
        args = self.native_fixture('shader_foliage'); args[4][0][BUCKET_FIELDS[0]] = source_density(args[0][0])
        self.assertTrue(native_density_issues(*args))
        args[3][0]['lightmap flags'] |= 1
        self.assertEqual(native_density_issues(*args), [])

    def test_shader_candidates_are_not_authority_to_rewrite_indices(self):
        args = self.native_fixture(); before = deepcopy(args)
        native_density_issues(*args)
        self.assertEqual(args[3], before[3])

    def test_old_saved_scene_cannot_receive_new_palette(self):
        with patch.dict(sys.modules, {'bpy': SimpleNamespace(context=SimpleNamespace(scene={}))}):
            with self.assertRaisesRegex(ValueError, 'predates exact density'):
                native_scene.configure_scenario(None, {'bsps': [{'authoring': {'materials': []}}]})


if __name__ == '__main__':
    unittest.main()

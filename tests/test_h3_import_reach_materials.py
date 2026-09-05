"""Native-node hookup planning without Blender or editing-kit files."""
import copy
import importlib
from pathlib import Path
import sys
from types import ModuleType
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry/h3_import'
NAME = 'h3_reach_plan_tests'
package = ModuleType(NAME); package.__path__ = [str(ROOT)]
sys.modules[NAME] = package
m = importlib.import_module(NAME + '.reach_materials')


def socket(name, kind='RGBA', visible=True):
    return {'name': name, 'type': kind, 'visible': visible}


class ReachMaterialTests(unittest.TestCase):
    def test_bitmap_rgb_and_alpha(self):
        p = {'name': 'base_map', 'type': 'bitmap'}
        self.assertEqual(m.parameter_bindings(p, [socket('base_map.rgb'), socket('base_map.a', 'VALUE')]),
                         [('base_map.rgb', 'color'), ('base_map.a', 'alpha')])

    def test_combined_socket_label(self):
        p = {'name': 'base_map', 'type': 'bitmap'}
        self.assertEqual(m.parameter_bindings(p, [socket('base_map.a/specular_mask.a', 'VALUE')]),
                         [('base_map.a/specular_mask.a', 'alpha')])

    def test_color_alpha_is_separate(self):
        sockets = [socket('albedo_color'), socket('albedo_color_alpha', 'VALUE')]
        self.assertEqual(len(m.parameter_bindings({'name': 'albedo_color', 'type': 'argb color'}, sockets)), 2)
        self.assertEqual(len(m.parameter_bindings({'name': 'albedo_color', 'type': 'color'}, sockets)), 1)

    def test_interface_alias(self):
        p = {'name': 'normal_specular_power', 'type': 'real'}
        sockets = [socket('specular_exponent_min', 'VALUE')]
        self.assertEqual(m.parameter_bindings(p, sockets), [])
        self.assertEqual(m.parameter_bindings(p, sockets, ['specular_exponent_min']),
                         [('specular_exponent_min', 'value')])

    def test_wrong_socket_type_not_coerced(self):
        p = {'name': 'albedo_color', 'type': 'argb color'}
        self.assertFalse(m.parameter_bindings(p, [socket('albedo_color', 'VALUE')]))
        self.assertFalse(m.parameter_bindings({'name': 'x', 'type': 'real'}, [socket('x', 'BOOLEAN')]))

    def test_inactive_sockets_not_connected(self):
        self.assertFalse(m.parameter_bindings({'name': 'base_map', 'type': 'bitmap'},
                                            [socket('base_map.rgb', visible=False)]))

    def test_source_not_mutated(self):
        p = {'name': 'base_map', 'type': 'bitmap', 'transform': [2, 3, 4, 5], 'has_functions': True}
        before = copy.deepcopy(p)
        m.parameter_bindings(p, [socket('base_map.rgb')])
        self.assertEqual(p, before)

    def test_no_fuzzy_parameter_guessing(self):
        self.assertFalse(m.parameter_bindings({'name': 'noise_map_a', 'type': 'bitmap'}, [socket('self_illum_map.rgb')]))

    def test_same_image_same_interpretation_reused(self):
        b = {'path': 'objects/test/image', 'index': 0, 'curve': 'linear'}
        self.assertEqual(m.staged_image_key(b, 'base_map'), m.staged_image_key(b, 'base_map'))

    def test_export_usage_separates_images(self):
        b = {'path': 'objects/test/image', 'index': 0, 'curve': 'linear'}
        self.assertNotEqual(m.staged_image_key(b, 'base_map'), m.staged_image_key(b, 'bump_map'))
        self.assertNotEqual(m.staged_image_key(b, 'bump_map'), m.staged_image_key(b, 'bump_detail_map'))

    def test_curve_and_index_are_part_of_identity(self):
        b = {'path': 'objects/test/image', 'index': 0, 'curve': 'linear'}
        self.assertNotEqual(m.staged_image_key(b, 'base_map'), m.staged_image_key(dict(b, curve='srgb'), 'base_map'))
        self.assertNotEqual(m.staged_image_key(b, 'base_map'), m.staged_image_key(dict(b, index=1), 'base_map'))

    def test_normal_usage_and_color_space(self):
        b = {'path': 'objects/test/image', 'index': 0, 'curve': 'srgb'}
        self.assertEqual(m.staged_image_key(b, 'bump_map')[2:], ('Non-Color', 'Normal Map (aka zbump)'))

    def test_full_source_path_names(self):
        self.assertNotEqual(m.stage_name('a/metal.shader'), m.stage_name('b/metal.shader'))
        self.assertEqual(m.stage_name(r'A\Metal.shader'), m.stage_name('a/metal.shader'))
        self.assertTrue(m.stage_name('a/metal.shader').startswith('h3_'))

    def test_unsafe_source_names_rejected(self):
        for source in ('../x.shader', 'D:/H3/tags/x.shader', '//x.shader'):
            with self.assertRaises(ValueError):
                m.stage_name(source)

    def test_other_families_not_silently_changed(self):
        with self.assertRaisesRegex(ValueError, 'ordinary'):
            m.validate_shader({'group': 'rmdc', 'source': 'x.shader_decal', 'status': 'resolved_snapshot'})

    def test_unresolved_not_staged(self):
        with self.assertRaisesRegex(ValueError, 'resolved'):
            m.validate_shader({'group': 'rmsh', 'source': 'x.shader', 'status': 'failed'})

    def test_categories_named_not_numbered(self):
        record = {'group': 'rmsh', 'source': 'x.shader', 'status': 'resolved_snapshot', 'parameters': [],
                  'categories': [{'category': 'self_illumination', 'option': 'illum_detail', 'source_index': 125},
                                 {'category': 'albedo', 'option': 'constant_color', 'source_index': 62}]}
        before = copy.deepcopy(record)
        categories, _ = m.validate_shader(record)
        self.assertEqual(categories['self_illumination']['option'], 'illum_detail')
        self.assertEqual(record, before)


if __name__ == '__main__':
    unittest.main()

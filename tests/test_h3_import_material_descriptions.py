"""Source-description validation without Blender or editing-kit data."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('source_materials', ROOT / 'blender/addons/io_scene_foundry/h3_import/materials.py')
materials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(materials)


def description(path='objects/test/test.shader'):
    return {'format': 'foundry.h3-material', 'version': 1, 'game': 'halo3_mcc',
        'source_shader': path, 'source_class': 'shader', 'source_group': 'rmsh',
        'description_status': 'partial', 'conversion_status': 'source_only', 'destination_shader': None,
        'definition': 'shaders/shader.render_method_definition',
        'categories': [{'category': 'albedo', 'option': 'default', 'source_option_index': 0}],
        'parameters': [{'name': 'base_map', 'type': 'bitmap', 'origin': 'option_default',
            'resolved': {'kind': 'bitmap', 'bitmap': 'textures/shared.bitmap'},
            'texture_transform': {'scale': [1.0, 1.0], 'translation': [0.0, 0.0]}}],
        'declarations': [{'default': {'name': 'base_map', 'bitmap_scale': 16.0}}],
        'source_parameters': [], 'diagnostics': [{'code': 'global_options_not_merged', 'message': 'Retained separately'}]}


def manifest_with_description():
    from h3_material_fixture import manifest
    value = manifest()
    value['shaders']['objects/test/test.shader']['source_description'] = description()
    return value


class SourceMaterialTests(unittest.TestCase):
    def validate(self, value):
        return materials.validate_source_description(value, value.get('source_shader'))

    def test_json_round_trip_retains_unknown_data_without_mutation(self):
        value = description()
        value['extra_source_data'] = {'raw': [1, 2, 3]}
        before = copy.deepcopy(value)
        self.assertEqual(self.validate(json.loads(json.dumps(value))), before)
        self.assertEqual(value, before)

    def test_legacy_preview_manifest_without_description_is_supported(self):
        from h3_material_fixture import manifest
        value = manifest()
        self.assertEqual(materials.validate_manifest(value, value['source_tag']), value)

    def test_new_description_is_part_of_existing_manifest_validation(self):
        value = manifest_with_description()
        materials.validate_manifest(value, value['source_tag'])
        value['shaders']['objects/test/test.shader']['source_description']['destination_shader'] = 'fake.shader'
        with self.assertRaises(ValueError):
            materials.validate_manifest(value, value['source_tag'])

    def test_errors_are_validated_even_when_preview_is_unresolved(self):
        value = manifest_with_description()
        shader = value['shaders']['objects/test/test.shader']
        shader['status'] = 'error'
        shader['source_description']['destination_shader'] = 'fake.shader'
        with self.assertRaises(ValueError):
            materials.validate_manifest(value, value['source_tag'])

    def test_description_diagnostics_reach_preview_report(self):
        shader = manifest_with_description()['shaders']['objects/test/test.shader']
        result = materials.plan(shader)
        self.assertTrue(any('global_options_not_merged' in d for d in result['diagnostics']))
        self.assertEqual(result['parameters']['base_map']['transform'], [2.0, 3.0, .25, -.5])

    def test_shared_bitmap_does_not_merge_materials(self):
        first, second = description(), description('objects/test/other.shader')
        second['parameters'][0]['texture_transform']['scale'] = [4.0, 2.0]
        self.assertIsNot(self.validate(first), self.validate(second))
        self.assertEqual(first['parameters'][0]['resolved']['bitmap'], second['parameters'][0]['resolved']['bitmap'])
        self.assertNotEqual(first['parameters'][0]['texture_transform'], second['parameters'][0]['texture_transform'])

    def test_names_and_defaults_survive_different_numeric_positions(self):
        value = description()
        value['categories'][0]['category_index'] = 7
        value['categories'][0]['source_option_index'] = 5
        result = self.validate(value)
        self.assertEqual(result['categories'][0]['option'], 'default')
        self.assertEqual(result['declarations'][0]['default']['bitmap_scale'], 16.0)

    def test_source_identity_is_path_based_not_basename_based(self):
        with self.assertRaises(ValueError):
            materials.validate_source_description(description('a/body.shader'), 'b/body.shader')
        self.assertEqual(materials.source_material_key('A\\BODY.shader'), 'a/body.shader')

    def test_unsafe_source_paths_are_rejected(self):
        for path in ('../body.shader', 'a/../body.shader', '/body.shader', 'C:\\body.shader', 'a//body.shader', 'body', 'a/./body.shader', 'a\x00.shader'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.validate(description(path))

    def test_source_class_must_match_path(self):
        with self.assertRaises(ValueError):
            self.validate(description('a.shader_water'))

    def test_source_description_cannot_assign_reach_destination(self):
        for path in ('objects/test/test.shader', 'mod/imported/test.shader', ''):
            value = description(); value['destination_shader'] = path
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.validate(value)

    def test_missing_destination_state_is_rejected(self):
        value = description(); del value['destination_shader']
        with self.assertRaises(ValueError):
            self.validate(value)

    def test_invalid_versions_are_rejected(self):
        for version in (2, True, 1.0, '1'):
            value = description(); value['version'] = version
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.validate(value)

    def test_nested_nonfinite_values_are_rejected(self):
        for n in (float('nan'), float('inf'), float('-inf')):
            value = description(); value['raw'] = {'nested': [n]}
            with self.subTest(number=n), self.assertRaises(ValueError):
                self.validate(value)

    def test_nonfinite_source_bits_remain_available(self):
        value = description(); value['source_parameters'] = [{'real': None, 'real_bits': 0x7fc01234}]
        self.assertEqual(self.validate(value)['source_parameters'][0]['real_bits'], 0x7fc01234)

    def test_transform_dimensions_and_types_are_checked(self):
        for scale in ([1.0], [True, 1.0], '1,1'):
            value = description(); value['parameters'][0]['texture_transform']['scale'] = scale
            with self.subTest(scale=scale), self.assertRaises(ValueError):
                self.validate(value)

    def test_failed_and_unsupported_records_keep_raw_fields(self):
        for status in ('failed', 'unsupported'):
            value = description(); value['description_status'] = status
            for key in ('parameters', 'categories', 'declarations', 'source_parameters', 'definition'):
                del value[key]
            value['source_parameter_fields'] = [{'unmapped': 5}]
            self.assertEqual(self.validate(value)['source_parameter_fields'], [{'unmapped': 5}])

    def test_raw_animations_and_externs_are_not_discarded(self):
        value = description()
        value['parameters'][0]['resolved'] = {'kind': 'extern', 'extern': 'scene ldr texture', 'value': None}
        value['source_parameter_fields'] = [{'animations': [{'function_data_hex': '00017f80ff', 'input_name': 'heat'}]}]
        self.assertEqual(self.validate(value), value)

    def test_raw_duplicate_parameters_are_retained_but_resolved_names_are_unique(self):
        value = description(); value['source_parameters'] = [{'name': 'base_map'}, {'name': 'base_map'}]
        self.validate(value)
        value['parameters'].append(copy.deepcopy(value['parameters'][0]))
        with self.assertRaises(ValueError):
            self.validate(value)

    def test_missing_resolved_fields_and_wrong_definition_class_are_rejected(self):
        for key in ('parameters', 'categories', 'declarations', 'source_parameters', 'definition'):
            value = description(); del value[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(value)
        value = description(); value['definition'] = 'shaders/shader.shader'
        with self.assertRaises(ValueError):
            self.validate(value)


if __name__ == '__main__':
    unittest.main()

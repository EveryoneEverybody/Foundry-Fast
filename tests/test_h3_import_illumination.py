"""Illumination selection without Blender or editing-kit dependencies."""
import copy
import importlib.util
from pathlib import Path
import unittest
from h3_illumination_fixture import manifest, set_option, SHADER

ROOT = Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry'
spec = importlib.util.spec_from_file_location('h3_illumination_materials', ROOT / 'h3_import/materials.py')
materials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(materials)


class IlluminationTests(unittest.TestCase):
    def test_fusion_coil_selects_additive(self):
        data = manifest()
        materials.validate_manifest(data, data['source_tag'])
        recipe = materials.plan(data['shaders'][SHADER])
        self.assertEqual(recipe['illumination_surface'], 'additive')
        self.assertEqual(recipe['parameters']['self_illum_detail_map']['transform'], [2, 2, 0, 0])
        self.assertEqual(recipe['parameters']['self_illum_intensity']['value'], 3)

    def test_supported_unlit_modes(self):
        for mode in sorted(materials.ILLUMINATION_MODES):
            for blend, expected in [('opaque', 'emission'), ('additive', 'additive')]:
                with self.subTest(mode=mode, blend=blend):
                    data = manifest()
                    set_option(data, 'self_illumination', mode)
                    set_option(data, 'blend_mode', blend)
                    self.assertEqual(materials.plan(data['shaders'][SHADER])['illumination_surface'], expected)

    def test_other_shader_families_are_not_treated_as_unlit_objects(self):
        for group in ['rmd ', 'rmhg', 'rmtr', None]:
            data = manifest(); data['shaders'][SHADER]['group'] = group
            self.assertEqual(materials.plan(data['shaders'][SHADER])['illumination_surface'], 'principled')

    def test_lit_models_remain_principled(self):
        for model in ['two_lobe_phong', 'cook_torrance', 'diffuse_only', 'unknown']:
            data = manifest(); set_option(data, 'material_model', model)
            self.assertEqual(materials.plan(data['shaders'][SHADER])['illumination_surface'], 'principled')

    def test_off_and_unsupported_illumination_remain_separate(self):
        for mode in ['off', 'none', 'plasma', 'meter', 'future_option']:
            data = manifest(); set_option(data, 'self_illumination', mode)
            self.assertEqual(materials.plan(data['shaders'][SHADER])['illumination_surface'], 'principled')

    def test_other_pass_requirements_do_not_select_additive_emission(self):
        for category, option in [('alpha_test', 'on'), ('environment_mapping', 'per_pixel'),
                                 ('blend_mode', 'alpha_blend'), ('blend_mode', 'multiply'),
                                 ('blend_mode', 'pre_multiplied_alpha')]:
            data = manifest(); set_option(data, category, option)
            self.assertEqual(materials.plan(data['shaders'][SHADER])['illumination_surface'], 'principled')

    def test_missing_material_model_is_not_guessed(self):
        data = manifest(); shader = data['shaders'][SHADER]
        shader['categories'] = [c for c in shader['categories'] if c['category'] != 'material_model']
        self.assertEqual(materials.plan(shader)['illumination_surface'], 'principled')

    def test_names_not_positions_and_no_source_mutation(self):
        data = manifest(); before = copy.deepcopy(data)
        original = materials.plan(data['shaders'][SHADER])
        self.assertEqual(data, before)
        data['shaders'][SHADER]['categories'].reverse()
        self.assertEqual(materials.plan(data['shaders'][SHADER])['illumination_surface'], original['illumination_surface'])
        self.assertNotIn('destination_shader', data['shaders'][SHADER])


if __name__ == '__main__':
    unittest.main()

"""Material identity, validation and preview planning tests."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from h3_material_fixture import manifest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('h3_materials', ROOT / 'blender/addons/io_scene_foundry/h3_import/materials.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class MaterialTests(unittest.TestCase):
    def test_valid_schema(self):
        data = manifest()
        self.assertIs(m.validate_manifest(data, data['source_tag']), data)

    def test_foreign_asset_rejected(self):
        with self.assertRaises(ValueError):
            m.validate_manifest(manifest(), 'different.model')

    def test_bad_schema_rejected(self):
        data = manifest(); data['version'] = 2
        with self.assertRaises(ValueError):
            m.validate_manifest(data, data['source_tag'])

    def test_duplicate_category_rejected(self):
        data = manifest(); shader = next(iter(data['shaders'].values()))
        shader['categories'].append(copy.deepcopy(shader['categories'][0]))
        with self.assertRaises(ValueError):
            m.validate_manifest(data, data['source_tag'])

    def test_duplicate_parameter_rejected(self):
        data = manifest(); shader = next(iter(data['shaders'].values()))
        shader['parameters'].append(copy.deepcopy(shader['parameters'][0]))
        with self.assertRaises(ValueError):
            m.validate_manifest(data, data['source_tag'])

    def test_nonfinite_rejected(self):
        data = manifest(); next(iter(data['shaders'].values()))['parameters'][-1]['value'][0] = float('nan')
        with self.assertRaises(ValueError):
            m.validate_manifest(data, data['source_tag'])

    def test_missing_bitmap_rejected(self):
        data = manifest(); data['bitmaps'].clear()
        with self.assertRaises(ValueError):
            m.validate_manifest(data, data['source_tag'])

    def test_colors_keep_rgba_order(self):
        shader = next(iter(manifest()['shaders'].values()))
        self.assertEqual(m.plan(shader)['parameters']['albedo_color']['value'], [.2, .4, .8, 1])

    def test_unknown_option_not_relabelled(self):
        shader = next(iter(manifest()['shaders'].values()))
        shader['categories'][0]['option'] = 'custom_test'
        recipe = m.plan(shader)
        self.assertEqual(recipe['albedo'], 'custom_test')
        self.assertTrue(any('base texture preview only' in s for s in recipe['diagnostics']))

    def test_unresolved_reference_keeps_placeholder(self):
        with self.assertRaises(ValueError):
            m.plan({'status': 'unresolved', 'error': 'Unresolved parent'})

    def test_same_basename_does_not_share_image(self):
        a = {'path': 'one/base', 'index': 0}; b = {'path': 'two/base', 'index': 0}
        self.assertNotEqual(m.image_key(a, 'color'), m.image_key(b, 'color'))

    def test_color_and_mask_are_separate(self):
        b = next(iter(manifest()['bitmaps'].values()))
        self.assertNotEqual(m.image_key(b, 'color'), m.image_key(b, 'data'))
        self.assertEqual(m.color_space(b, 'color'), 'sRGB')
        self.assertEqual(m.color_space(b, 'data'), 'Non-Color')

    def test_linear_color_stays_linear(self):
        self.assertEqual(m.color_space({'curve': 'Linear'}, 'color'), 'Non-Color')

    def test_opaque_alpha_is_not_a_blend(self):
        shader = next(iter(manifest()['shaders'].values()))
        self.assertEqual(m.plan(shader)['categories']['blend_mode'], 'opaque')

    def test_preview_path_validation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / 'texture.tif').touch()
            self.assertEqual(m.preview_path(root, 'texture.tif'), root / 'texture.tif')
            for bad in ['../texture.tif', '/texture.tif', 'C:\\texture.tif', '\\\\server\\texture.tif', 'a//texture.tif', 'texture.exe']:
                with self.assertRaises((ValueError, OSError)):
                    m.preview_path(root, bad)

    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as out:
            target = Path(out) / 'escape.tif'; target.touch()
            link = Path(d) / 'escape.tif'
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest('Symlinks unavailable')
            with self.assertRaises(ValueError):
                m.preview_path(d, 'escape.tif')

    def test_duplicate_json_key_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'shader_manifest.json'; path.write_text('{"format":1,"format":2}')
            with self.assertRaises(ValueError):
                m.load_manifest(path, 'test')

    def test_snapshot_does_not_remove_functions(self):
        data = manifest(); shader = next(iter(data['shaders'].values()))
        shader['parameters'][0]['has_functions'] = True
        shader['authored_parameters'] = [{'functions': [{'function_hex': '00ff80'}]}]
        original = copy.deepcopy(data)
        m.plan(shader)
        self.assertEqual(data, original)


if __name__ == '__main__':
    unittest.main()

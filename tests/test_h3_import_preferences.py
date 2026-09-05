"""Source-setting checks without Blender or game data."""
import ast
import importlib.util
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry'
IMPORTER = ast.parse((ROOT / 'h3_import/__init__.py').read_text(encoding='utf-8'))
PREFERENCES = ast.parse((ROOT / 'preferences.py').read_text(encoding='utf-8'))
OPERATOR = next(n for n in IMPORTER.body if isinstance(n, ast.ClassDef) and n.name == 'NWO_OT_ImportHalo3Object')
spec = importlib.util.spec_from_file_location('h3_preferences_core', ROOT / 'h3_import/core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


class Layout:
    def __init__(self):
        self.properties = []
        self.labels = []
        self.enabled = True

    def label(self, *, text):
        self.labels.append(text)

    def prop(self, owner, name):
        self.properties.append(name)

    def row(self):
        return self


def load_functions(namespace):
    nodes = [n for n in IMPORTER.body if isinstance(n, ast.FunctionDef) and n.name == '_source_paths']
    nodes += [n for n in OPERATOR.body if isinstance(n, ast.FunctionDef) and n.name in {'draw', 'invoke'}]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / 'h3_import/__init__.py'), 'exec'), namespace)


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'H3EK/tags'
        self.root.mkdir(parents=True)
        self.source = self.root / 'objects/fusion_coil/fusion_coil.crate'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b'fixture only')
        self.destination = self.base / 'Reach/tags'
        self.destination.mkdir(parents=True)
        self.helper = self.base / 'helper.exe'
        self.helper.write_bytes(b'not executable; resolution only')
        self.prefs = SimpleNamespace(h3_tags_root='', h3_extraction_helper='')
        self.invoke_base = Mock(return_value={'RUNNING_MODAL'})
        self.ns = {
            'Path': Path, 'os': os,
            'bpy': SimpleNamespace(path=SimpleNamespace(abspath=lambda p: p)),
            'utils': SimpleNamespace(get_prefs=lambda: self.prefs, get_tags_path=lambda: str(self.destination)),
            'find_tags_root': core.find_tags_root,
            '_bundled_helper_path': lambda: self.helper,
            'ImportHelper': SimpleNamespace(invoke=self.invoke_base),
        }
        load_functions(self.ns)

    def test_automatic_paths_without_project_xml(self):
        self.assertEqual(self.ns['_source_paths'](self.source), (self.root, self.helper))
        self.assertFalse((self.root.parent / 'project.xml').exists())

    def test_saved_directory_with_nonstandard_name(self):
        custom = self.base / 'source_assets'
        custom.mkdir()
        source = custom / 'sample.model'
        source.touch()
        self.prefs.h3_tags_root = str(custom)
        self.assertEqual(self.ns['_source_paths'](source)[0], custom)

    def test_current_preferences_are_read_for_each_import(self):
        other = self.base / 'second_source'
        other.mkdir()
        source = other / 'sample.model'
        source.touch()
        self.prefs.h3_tags_root = str(self.root)
        self.ns['_source_paths'](self.source)
        self.prefs.h3_tags_root = str(other)
        self.assertEqual(self.ns['_source_paths'](source)[0], other)

    def test_helper_override(self):
        custom = self.base / 'custom.exe'
        custom.touch()
        self.prefs.h3_extraction_helper = str(custom)
        self.assertEqual(self.ns['_source_paths'](self.source)[1], custom)

    def test_invalid_directory(self):
        self.prefs.h3_tags_root = str(self.base / 'missing')
        with self.assertRaisesRegex(NotADirectoryError, 'Foundry preferences'):
            self.ns['_source_paths'](self.source)

    def test_outside_configured_directory(self):
        other = self.base / 'other'
        other.mkdir()
        self.prefs.h3_tags_root = str(other)
        with self.assertRaisesRegex(ValueError, 'outside the configured'):
            self.ns['_source_paths'](self.source)

    def test_reach_directory_rejected(self):
        self.ns['utils'].get_tags_path = lambda: str(self.root)
        with self.assertRaisesRegex(ValueError, 'must be different'):
            self.ns['_source_paths'](self.source)

    def test_missing_helper_override_does_not_fall_back(self):
        self.prefs.h3_extraction_helper = str(self.base / 'missing.exe')
        with self.assertRaisesRegex(FileNotFoundError, 'Extraction Helper Override'):
            self.ns['_source_paths'](self.source)

    def test_missing_tags_ancestor_explains_preferences(self):
        source = self.base / 'sample.model'
        source.touch()
        with self.assertRaisesRegex(ValueError, 'Foundry preferences'):
            self.ns['_source_paths'](source)

    def test_import_draw_has_no_path_widgets(self):
        layout = Layout()
        self.ns['draw'](SimpleNamespace(layout=layout, preview_materials=True), None)
        self.assertEqual(layout.properties, ['import_collision', 'import_physics', 'reference_only', 'preview_materials', 'flip_normal_green'])
        self.assertIn('H3 tags: Auto-detect', layout.labels)
        self.assertIn('Helper: Bundled', layout.labels)

    def test_import_draw_reports_saved_settings(self):
        self.prefs.h3_tags_root = str(self.root)
        self.prefs.h3_extraction_helper = str(self.helper)
        layout = Layout()
        self.ns['draw'](SimpleNamespace(layout=layout, preview_materials=True), None)
        self.assertIn('H3 tags: Saved preference', layout.labels)
        self.assertIn('Helper: Preference override', layout.labels)

    def test_normal_toggle_disabled_without_previews(self):
        layout = Layout()
        self.ns['draw'](SimpleNamespace(layout=layout, preview_materials=False), None)
        self.assertFalse(layout.enabled)

    def test_file_browser_starts_at_saved_directory(self):
        self.prefs.h3_tags_root = str(self.root)
        operator = SimpleNamespace(filepath='')
        self.assertEqual(self.ns['invoke'](operator, None, None), {'RUNNING_MODAL'})
        self.assertEqual(operator.filepath, str(self.root) + os.sep)
        self.invoke_base.assert_called_once_with(operator, None, None)

    def test_explicit_file_path_is_preserved(self):
        self.prefs.h3_tags_root = str(self.root)
        operator = SimpleNamespace(filepath=str(self.source))
        self.ns['invoke'](operator, None, None)
        self.assertEqual(operator.filepath, str(self.source))

    def test_path_properties_belong_to_preferences(self):
        cls = next(n for n in PREFERENCES.body if isinstance(n, ast.ClassDef) and n.name == 'FoundryPreferences')
        fields = {n.target.id: n for n in cls.body if isinstance(n, ast.AnnAssign)}
        for name, subtype in [('h3_tags_root', 'DIR_PATH'), ('h3_extraction_helper', 'FILE_PATH')]:
            kw = {k.arg: k.value for k in fields[name].annotation.keywords}
            self.assertEqual(ast.literal_eval(kw['subtype']), subtype)
            self.assertEqual(ast.unparse(kw['options']), 'set()')
        op_fields = {n.target.id for n in OPERATOR.body if isinstance(n, ast.AnnAssign)}
        self.assertNotIn('tags_root', op_fields)
        self.assertNotIn('helper_path', op_fields)


if __name__ == '__main__':
    unittest.main()

"""Register real preference and importer classes with isolated Foundry stubs.

No game tags, ManagedBlam session, or interactive file browser is exercised.
"""
import ast
import importlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import bpy

ROOT = Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry'
NAME = 'foundry_h3_preferences_smoke'
package = ModuleType(NAME)
package.__path__ = [str(ROOT)]
sys.modules[NAME] = package
startup = ModuleType(NAME + '.startup')
startup.load_handler_complete = True
sys.modules[startup.__name__] = startup
utils = ModuleType(NAME + '.utils')
parsed = ast.parse((ROOT / 'preferences.py').read_text(encoding='utf-8'))
for node in parsed.body:
    if isinstance(node, ast.ImportFrom) and node.module == 'utils':
        for alias in node.names:
            setattr(utils, alias.name, lambda *a, **kw: None)
settings = SimpleNamespace(scale='blender', forward_direction='x', maintain_marker_axis=True, export_in_progress=False)
utils.get_scene_props = lambda: settings
utils.addon_root = lambda: str(ROOT)
utils.current_project_valid = lambda: True
utils.is_corinth = lambda context: False
sys.modules[utils.__name__] = utils
managed = ModuleType(NAME + '.managed_blam')
managed.__path__ = [str(ROOT / 'managed_blam')]
sys.modules[managed.__name__] = managed
tools = ModuleType(NAME + '.tools')
tools.__path__ = [str(ROOT / 'tools')]
sys.modules[tools.__name__] = tools
preferences = importlib.import_module(NAME + '.preferences')
preferences.register()
addon = bpy.context.preferences.addons.new()
addon.module = NAME
utils.get_prefs = lambda: bpy.context.preferences.addons[NAME].preferences
prefs = utils.get_prefs()
assert prefs.bl_rna.identifier == 'FoundryPreferences'
assert prefs.h3_tags_root == ''
assert prefs.h3_extraction_helper == ''
assert prefs.bl_rna.properties['h3_tags_root'].subtype == 'DIR_PATH'
assert prefs.bl_rna.properties['h3_extraction_helper'].subtype == 'FILE_PATH'
importer = importlib.import_module(NAME + '.h3_import')
importer.register()
rna = bpy.ops.nwo.import_halo3_object.get_rna_type()
assert 'tags_root' not in rna.properties
assert 'helper_path' not in rna.properties
for name in ['import_collision', 'import_physics', 'reference_only']:
    assert name in rna.properties

class Layout:
    def __init__(self):
        self.properties = []
        self.labels = []
    def box(self):
        return self
    def row(self, **kwargs):
        return self
    def column(self, **kwargs):
        return self
    def label(self, *, text, **kwargs):
        self.labels.append(text)
    def prop(self, owner, name, **kwargs):
        assert name in owner.bl_rna.properties
        self.properties.append((owner, name))
    def template_list(self, *args, **kwargs):
        pass
    def operator(self, *args, **kwargs):
        return SimpleNamespace()
    def separator(self):
        pass

layout = Layout()
preferences.draw_foundry_preferences(layout, prefs)
assert (prefs, 'h3_tags_root') in layout.properties
assert (prefs, 'h3_extraction_helper') in layout.properties
assert 'Halo 3 Import (Experimental)' in layout.labels
with TemporaryDirectory() as folder:
    base = Path(folder).resolve()
    source_root = base / 'H3EK/tags'
    source_root.mkdir(parents=True)
    source = source_root / 'sample.crate'
    source.touch()
    helper = base / 'helper.exe'
    helper.touch()
    destination = base / 'Reach/tags'
    destination.mkdir(parents=True)
    utils.get_tags_path = lambda: str(destination)
    prefs.h3_tags_root = str(source_root)
    prefs.h3_extraction_helper = str(helper)
    assert importer._source_paths(source) == (source_root, helper)
    assert not (source_root.parent / 'project.xml').exists()
    prefs.h3_tags_root = ''
    assert importer._source_paths(source)[0] == source_root
    assert utils.get_tags_path() == str(destination)
importer.unregister()
bpy.context.preferences.addons.remove(addon)
for cls in reversed(preferences.classes):
    bpy.utils.unregister_class(cls)
print('H3 preference smoke test passed: real preference registration, draw bindings, operator properties and source resolution')

"""Exercise registered normal Foundry import routing with detached decoder spies."""
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import bpy

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'blender/addons'))
bpy.ops.preferences.addon_enable(module='io_scene_foundry')
from io_scene_foundry import h3_import, utils
from io_scene_foundry.h3_import import scenario_ui
from io_scene_foundry.tools import importer

calls = []
class Job:
    def __init__(self, owner, options):
        calls.append((owner.bl_idname, options, utils.get_tags_path(), utils.get_scene_props().scene_project))
    def execute(self, context): return {'FINISHED'}

with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    reach = base/'Reach/tags'; h3 = base/'H3EK/tags'
    reach.mkdir(parents=True); h3.mkdir(parents=True)
    for folder in (reach, h3): (folder/'test.scenario').touch()
    prefs = utils.get_prefs()
    prefs.projects.clear()
    project = prefs.projects.add(); project.name = 'Omaha'; project.project_path = str(reach.parent)
    project.tags_directory = str(reach); project.data_directory = str(reach.parent/'data')
    utils.get_scene_props().scene_project = 'Omaha'
    prefs.h3_tags_root = str(h3)
    with patch.object(h3_import, 'ScenarioImportJob', Job), patch.object(importer, 'start_mb_for_import') as mb:
        result = bpy.ops.nwo.foundry_import(filepath=str(h3/'test.scenario'),
            tag_sky='h3:1', tag_bsp_import_geometry=False, tag_scenario_import_objects=True,
            build_blender_materials=True, h3_inspect_firing_positions=True)
        assert result == {'FINISHED'}
        mb.assert_not_called()
    name, options, tags, project = calls[-1]
    assert name == 'NWO_OT_foundry_import' or name == 'nwo.foundry_import', name
    assert tags == str(reach) and project == 'Omaha'
    assert options.sky == 'h3:1' and not options.geometry and options.objects and options.materials
    assert options.firing_positions and not options.ai and not options.giant_hints
    assert utils.get_scene_props().scene_project == 'Omaha'

    # Stop exactly at the existing Reach backend boundary, before opening synthetic bytes.
    reached = []
    def reach_backend(path):
        reached.append(path)
        raise RuntimeError('test Reach backend boundary')
    with patch.object(h3_import, 'ScenarioImportJob', Job), patch.object(importer, 'start_mb_for_import', reach_backend):
        try: bpy.ops.nwo.foundry_import(filepath=str(reach/'test.scenario'))
        except RuntimeError: pass
    assert reached == [str(reach/'test.scenario')]
    assert len(calls) == 1
    unknown = base/'unknown.scenario'; unknown.touch()
    with patch.object(importer, 'start_mb_for_import') as mb:
        try: result = bpy.ops.nwo.foundry_import(filepath=str(unknown))
        except RuntimeError as error: assert 'Unknown scenario source' in str(error)
        else: assert result == {'CANCELLED'}
        mb.assert_not_called()

    for op in (bpy.ops.nwo.foundry_import, bpy.ops.nwo.import_from_drop):
        props = op.get_rna_type().properties
        assert all(not props[name].default for name in scenario_ui.INSPECTION_PROPERTIES)
        assert {'tag_sky', 'tag_scenario_import_objects', 'tag_bsp_import_geometry', 'build_blender_materials'} <= set(props.keys())
    # Actual collection property callbacks match Foundry colors, with no false roles.
    col = bpy.data.collections.new('semantic test')
    for semantic, color in [('region', 'COLOR_05'), ('permutation', 'COLOR_04'), ('exclude', 'COLOR_01')]:
        col.nwo.type = semantic
        assert col.color_tag == color
    bpy.data.collections.remove(col)

print('Registered Foundry operator passed: shared properties, H3 routing, unchanged Reach boundary, source rejection, project preservation and collection colors')

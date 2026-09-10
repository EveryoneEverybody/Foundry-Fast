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
from io_scene_foundry.h3_import import scenario_ui, scenario_assets
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
    skies = [dict(index=0, source_tag='levels/test/sky/sky.scenery'),
             dict(index=1, source_tag='levels/test/sky/clouds.scenery')]
    # The actual RNA wrappers passed to property callbacks forbid Python attrs.
    normal = bpy.context.window_manager.operator_properties_last('nwo.foundry_import')
    drop = bpy.context.window_manager.operator_properties_last('nwo.import_from_drop')
    assert isinstance(normal, bpy.types.OperatorProperties)
    assert isinstance(drop, bpy.types.OperatorProperties)
    normal.filepath = drop.filepath = str(h3/'test.scenario')
    try: normal._scenario_selection_key = 'must fail'
    except AttributeError: pass
    else: raise AssertionError('Regression fixture must use a restricted RNA wrapper')
    scenario_ui._selection_state.cache_clear()
    with patch.object(scenario_ui, 'selection', return_value=skies) as decode:
        for _ in range(3):
            suggestions = scenario_ui.search_skies(normal, bpy.context, '')
            assert suggestions == (('0: levels/test/sky/sky.scenery', 'levels/test/sky/sky.scenery'),
                                   ('1: levels/test/sky/clouds.scenery', 'levels/test/sky/clouds.scenery'))
            scenario_ui.refresh(normal)
            # Assignment invokes Blender's dynamic EnumProperty callback.
            drop.tag_sky = 'h3:1'
            assert drop.tag_sky == 'h3:1'
        assert decode.call_count == 1
        for value in ('0', 'h3:0', 'sky', 'sky.scenery', suggestions[0][0],
                      'LEVELS\\TEST\\SKY\\SKY.SCENERY'):
            assert scenario_assets.selected_sky(skies, value)['index'] == 0
        with patch.object(h3_import, 'ScenarioImportJob', Job), patch.object(importer, 'start_mb_for_import') as mb:
            for value in ('sky0', '99'):
                try: bpy.ops.nwo.foundry_import(filepath=normal.filepath, tag_sky=value)
                except RuntimeError as error: assert 'Choose from the Sky search' in str(error)
                else: raise AssertionError('Invalid sky must fail before starting a scenario job')
            assert not calls
            mb.assert_not_called()
        # Source changes invalidate cached rows; reopening another source cannot
        # inherit the previous source's classification, error or sky entries.
        (h3/'test.scenario').write_bytes(b'changed source')
        scenario_ui.search_skies(normal, bpy.context, '')
        assert decode.call_count == 2
        normal.filepath = str(reach/'test.scenario')
        assert not scenario_ui.search_skies(normal, bpy.context, '')
        assert scenario_ui.selection_state(normal).source == 'reach'
        assert decode.call_count == 2
        normal.filepath = str(h3/'missing.scenario')
        assert not scenario_ui.search_skies(normal, bpy.context, '')
        assert scenario_ui.selection_state(normal).error
        normal.filepath = str(h3/'test.scenario')
        assert not scenario_ui.selection_state(normal).error
    with patch.object(scenario_ui, 'selection', return_value=skies), \
            patch.object(h3_import, 'ScenarioImportJob', Job), patch.object(importer, 'start_mb_for_import') as mb:
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

print('Registered Foundry operator passed: RNA sky search/enum callbacks, source cache invalidation, early sky validation, shared properties, H3 routing, unchanged Reach boundary, source rejection, project preservation and collection colors')

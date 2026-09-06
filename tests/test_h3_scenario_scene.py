"""Source manifest and exact authored-hint resolution tests."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest

from h3_scenario_fixture import bsp, instance, inventory, scene, write_bundle, BSP, SCENARIO
ROOT=Path(__file__).resolve().parents[1]
PKG='h3_scenario_test'
package=ModuleType(PKG);package.__path__=[str(ROOT/'blender/addons/io_scene_foundry/h3_import')];sys.modules[PKG]=package
m=importlib.import_module(PKG+'.scenario_scene')


class SceneTests(unittest.TestCase):
    def test_valid_is_not_mutated(self):
        data=bsp();before=deepcopy(data);self.assertIs(m.validate_bsp(data,BSP,0),data);self.assertEqual(data,before)
    def test_wrong_source(self):
        with self.assertRaises(ValueError):m.validate_bsp(bsp(),'other.scenario_structure_bsp',0)
        with self.assertRaises(ValueError):m.validate_scene(scene(),'other.scenario')
    def test_boolean_version_is_not_version(self):
        data=bsp();data['version']=True
        with self.assertRaises(ValueError):m.validate_bsp(data,BSP,0)
    def test_source_materials_cannot_write_reach_paths(self):
        data=bsp();data['materials'][0]['destination_shader']='objects/a.shader'
        with self.assertRaises(ValueError):m.validate_bsp(data,BSP,0)
    def test_same_names_keep_material_slots(self):
        data=m.validate_bsp(bsp(),BSP,0)
        self.assertEqual(len(data['materials']),2);self.assertNotEqual(data['materials'][0]['source_shader'],data['materials'][1]['source_shader'])
    def test_bad_vertex_index(self):
        data=bsp();data['objects'][0]['triangles'][0]['vertices'][0]=3
        with self.assertRaises(ValueError):m.validate_bsp(data,BSP,0)
    def test_nonfinite_uv(self):
        data=bsp();data['objects'][0]['vertices'][0]['uvs'][0][2]=float('nan')
        with self.assertRaises(ValueError):m.validate_bsp(data,BSP,0)
    def test_unassigned_material_retained(self):
        data=bsp();data['objects'][0]['triangles'][0]['material']=-1;m.validate_bsp(data,BSP,0)
        self.assertEqual(data['objects'][0]['triangles'][0]['material'],-1)
    def test_negative_scale_retained(self):
        data=m.validate_bsp(bsp(),BSP,0);self.assertEqual(data['instances'][0]['scale'],-2)
    def test_out_of_order_parents(self):
        self.assertEqual([i['id'] for i in m.placement_order(bsp()['instances'])],[0,2,1])
    def test_missing_and_cyclic_parent(self):
        for parent in (33,1):
            data=bsp();data['instances'][2]['parent']=parent
            with self.assertRaises(ValueError):m.validate_bsp(data,BSP,0)
    def test_duplicate_instance_id(self):
        data=bsp();data['instances'][1]['id']=2
        with self.assertRaises(ValueError):m.validate_bsp(data,BSP,0)
    def test_singular_transform(self):
        for key,value in [('scale',0),('rotation',[0,0,0,0])]:
            data=bsp();data['instances'][0][key]=value
            with self.assertRaises(ValueError):m.validate_bsp(data,BSP,0)
    def test_scene_blob_and_geometry_paths(self):
        with tempfile.TemporaryDirectory() as d:
            write_bundle(d,True);data,raw=m.load_scene(Path(d)/'scene.h3scene.json',SCENARIO)
            self.assertEqual(len(data['bsp_entries']),1);self.assertEqual(raw['records'][-1]['bytes'],4)
    def test_geometry_path_cannot_escape(self):
        data=scene();data['bsp_entries'][0]['geometry']='../bsp_0000.json'
        with self.assertRaises(ValueError):m.validate_scene(data)
    def test_symlink_escape(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as other:
            target=Path(other)/'file';target.touch();link=Path(d)/'link'
            try:link.symlink_to(target)
            except OSError:self.skipTest('Symlinks unavailable')
            with self.assertRaises(ValueError):m.within(d,'link')
    def test_duplicate_json_key(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'data.json';path.write_text('{"a":1,"a":2}')
            with self.assertRaises(ValueError):m.checked_json(path)
    def test_explicit_bsp_selection(self):
        self.assertIsNone(m.bsp_selection(''));self.assertEqual(m.bsp_selection('2, 0'),{0,2})
        for text in ('0,0','-1','64','2,','1.0'):
            with self.assertRaises(ValueError):m.bsp_selection(text)


class HintTests(unittest.TestCase):
    def test_source_order_and_units(self):
        data=inventory();before=deepcopy(data);plan=m.hint_plan(data)
        self.assertEqual(plan['sectors'][0]['points'],[[0,0,0],[2,0,0],[0,2,0]])
        self.assertTrue(plan['sectors'][0]['closed']);self.assertEqual(data,before)
    def test_rail_resolves_line_index_zero(self):
        row=m.hint_plan(inventory())['rails'][0]
        self.assertEqual(row['points'],[[0,0,0],[2,0,0]]);self.assertFalse(row['closed'])
        self.assertEqual(row['flags']['value'],1);self.assertEqual(row['bsp_indices'],[0,0])
    def test_invalid_rail_is_reported_not_guessed(self):
        data=inventory();next(r for r in data['records'] if r['name']=='geometry index')['value']=-1
        plan=m.hint_plan(data);self.assertFalse(plan['rails']);self.assertTrue(plan['diagnostics'])
    def test_object_relative_sector_is_not_drawn_in_world(self):
        data=inventory();next(r for r in data['records'] if r['name']=='reference frame')['value']=0
        plan=m.hint_plan(data);self.assertFalse(plan['sectors']);self.assertEqual(len(plan['rails']),1)
    def test_object_relative_rail_not_partially_drawn(self):
        data=inventory();next(r for r in data['records'] if r['name']=='reference frame 1')['value']=0
        plan=m.hint_plan(data);self.assertFalse(plan['rails']);self.assertTrue(plan['diagnostics'])
    def test_missing_point_not_replaced_with_zero(self):
        data=inventory();data['records']=[r for r in data['records'] if not (r['name']=='point' and '/points#' in r['address'] and '[1]/' in r['address'])]
        self.assertFalse(m.hint_plan(data)['sectors'])
    def test_firing_position_zone_and_area(self):
        row=m.hint_plan(inventory())['firing_positions'][0]
        self.assertEqual(row['name'],'scarab_zone/platform/fp_0');self.assertEqual(row['points'],[[1,2,3]])
        self.assertEqual(row['zone_flags']['set_bits'][0][1],'giants zone')
    def test_script_point_names_preserved(self):
        self.assertEqual(m.hint_plan(inventory())['script_points'][0]['name'],'ps_scarab/p0')
    def test_ambiguous_field_reported(self):
        data=inventory();row=deepcopy(next(r for r in data['records'] if r['name']=='geometry index'));row['address']+='9';data['records'].append(row)
        self.assertFalse(m.hint_plan(data)['rails'])
    def test_schema_field_names_match_pinned_h3_definitions(self):
        path=ROOT/'.cache/reference-definitions/halo3_mcc/scenario.json'
        if not path.is_file():self.skipTest('Pinned definitions are provided by CI')
        structs=json.loads(path.read_text())['structs']
        for struct,field in [('user_hint_giant_sector_block','points'),('user_hint_giant_rail_block','geometry index*'),
                             ('user_hint_sector_point_block','reference frame*'),('user_hint_line_segment_block','Point 0')]:
            self.assertIn(field,[f.get('name') for f in structs[struct]['fields']])


class ScenarioUITests(unittest.TestCase):
    def test_scenario_controls_reuse_existing_importer(self):
        from test_h3_import_preferences import IMPORTER, OPERATOR, Layout, load_functions
        from types import SimpleNamespace
        layout = Layout()
        ns = {'Path': Path, 'utils': SimpleNamespace(get_prefs=lambda: SimpleNamespace(h3_tags_root='', h3_extraction_helper=''))}
        load_functions(ns)
        ns['draw'](SimpleNamespace(layout=layout, filepath='040_voi.scenario', preview_materials=True), None)
        self.assertEqual(layout.properties, ['scenario_geometry','scenario_bsp_indices','scenario_hints','scenario_points','preview_materials','flip_normal_green'])
        self.assertNotIn('reference_only',layout.properties)
        self.assertNotIn('h3_tags_root',layout.properties)

    def test_log_does_not_break_empty_output_contract(self):
        import ast
        from types import SimpleNamespace
        from unittest.mock import Mock
        from test_h3_import_preferences import IMPORTER, OPERATOR
        log_output = importlib.import_module(PKG + '.import_output')
        code = next(n for n in OPERATOR.body if isinstance(n, ast.FunctionDef) and n.name == 'execute')
        # Execute the production routing with the process launcher replaced.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve();tags=root/'tags';tags.mkdir();tag=tags/'040_voi.scenario';tag.touch()
            helper=root/'h3-object-bridge';helper.touch();(root/'h3-scenario-inspect').touch()
            output=root/'temporary';output.mkdir()
            popen=Mock(return_value=SimpleNamespace(poll=lambda:None))
            settings=SimpleNamespace(export_in_progress=False)
            wm=SimpleNamespace(event_timer_add=Mock(),modal_handler_add=Mock())
            context=SimpleNamespace(scene=object(),view_layer=SimpleNamespace(objects=SimpleNamespace(active=None)),area=None,selected_objects=[],window_manager=wm,window=None)
            operator=SimpleNamespace(filepath=str(tag),scenario_geometry=True,scenario_bsp_indices='',import_collision=True,import_physics=True,report=Mock(),_finish=Mock())
            ns={'Path':Path,'os':SimpleNamespace(name='posix'),'time':SimpleNamespace(monotonic=lambda:0),
                'bpy':SimpleNamespace(path=SimpleNamespace(abspath=lambda p:p)),
                'utils':SimpleNamespace(get_scene_props=lambda:settings,show_output=Mock()),'HelperLogTail':log_output.HelperLogTail,
                'open_output':log_output.open_output,'_source_paths':lambda p:(tags,helper),
                'tempfile':SimpleNamespace(mkdtemp=lambda **kw:str(output)),
                'subprocess':SimpleNamespace(Popen=popen,STDOUT=-2),'_active':[],
                '__package__':PKG,'traceback':SimpleNamespace(print_exc=Mock())}
            exec(compile(ast.Module(body=[code],type_ignores=[]),'h3_import/execute','exec'),ns)
            try:
                self.assertEqual(ns['execute'](operator,context),{'RUNNING_MODAL'})
                ns['utils'].show_output.assert_called_once_with()
                command=popen.call_args.args[0]
                directory=Path(command[command.index('--output')+1])
                self.assertEqual(list(directory.iterdir()),[])
                self.assertNotEqual(operator._log_path.parent,directory)
                self.assertIn('--geometry',command)
                self.assertNotIn('--collision',command)
                self.assertNotIn('--physics',command)
            finally:
                if getattr(operator, '_log', None):operator._log.close()


if __name__=='__main__':unittest.main()

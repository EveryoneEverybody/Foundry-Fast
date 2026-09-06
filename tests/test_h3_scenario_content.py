from copy import deepcopy
import importlib
import unittest
from test_h3_scenario_scene import PKG
from h3_scenario_content_fixture import content_inventory
from h3_material_fixture import manifest
from h3_import_fixture import payload

c = importlib.import_module(PKG+'.scenario_content')
objects = importlib.import_module(PKG+'.scenario_objects')
materials = importlib.import_module(PKG+'.materials')


class ContentTests(unittest.TestCase):
    def test_repeated_palettes_preserve_instance_identity(self):
        data=content_inventory();before=deepcopy(data);plan=c.plan(data)
        self.assertEqual(data,before)
        rows=plan['placements'];self.assertEqual(len(rows),6)
        self.assertEqual([r['name'] for r in rows[:3]],['gate_a','gate_b','gate_variant'])
        self.assertEqual([r['variant'] for r in rows[:3]],['default','default','alternate'])
        self.assertEqual(rows[0]['source_tag'],'objects/test/panel.scenery')
        self.assertEqual(rows[3]['source_tag'],'objects/test/panel.device_machine')
        self.assertEqual(rows[5]['source_tag'],'objects/test/panel.crate')
        self.assertEqual(rows[0]['source_scale'],0);self.assertEqual(rows[0]['scale'],1)
        self.assertEqual(rows[1]['position'],[11,20,30]);self.assertEqual(rows[1]['rotation'],[.5,.25,-.1])
        self.assertEqual(rows[1]['scale'],2);self.assertEqual(rows[1]['folder'],1)
        self.assertEqual(len(objects.requests(plan)),3)
    def test_authored_groups_and_points(self):
        plan=c.plan(content_inventory());groups={g['key']:g for g in plan['groups']}
        self.assertEqual(groups['folder:1']['parent'],'folder:0')
        self.assertEqual(groups['squad:0']['parent'],'squad-group:0')
        self.assertEqual(groups['objective:0/task:0']['area_references'],[dict(zone=0,area=0)])
        self.assertEqual(groups['designer-zone:0']['palette_references'],{'giants':[{'palette index':0}]})
        self.assertEqual({r['kind'] for r in plan['overlays']},{'trigger volumes','player starting locations','cutscene flags','cutscene camera points','squad starts'})
    def test_unresolved_palette_keeps_transform(self):
        data=content_inventory();row=next(r for r in data['records'] if r['name']=='type');row['value']=999
        row=c.plan(data)['placements'][0]
        self.assertIsNone(row['source_tag']);self.assertEqual(row['position'],[10,20,30]);self.assertTrue(row['diagnostics'])
    def test_untyped_euler_and_attachment_are_not_guessed(self):
        for name,value in [('rotation',{'decoder_debug':'RealEulerAngles3d(rounded)'}),('parent object',1)]:
            data=content_inventory();next(r for r in data['records'] if r['name']==name)['value']=value
            row=c.plan(data)['placements'][0];self.assertIsNone(row['position']);self.assertTrue(row['diagnostics'])
    def test_unsafe_source_rejected(self):
        with self.assertRaises(ValueError):c.tag_reference(dict(path='../outside',extension='scenery'))
    def test_variant_selection_and_ambiguous_state(self):
        data=payload();data['variants']=[dict(name='default',regions=[dict(name='body',parent_variant=-1,permutations=[dict(name='default',states=[{'state':1}])])])]
        selected,diagnostics=objects.variant_regions(data,'default')
        self.assertEqual(selected,{'body':{'default'}});self.assertTrue(diagnostics)
        data['variants'][0]['regions'][0]['permutations'].append(dict(name='alternate'))
        self.assertEqual(objects.variant_regions(data,'default')[0],{})
        self.assertIsNone(objects.variant_regions(data,'missing')[0])


class MaterialResolutionTests(unittest.TestCase):
    def test_precise_failure_stages(self):
        record=dict(source_shader='objects/test/test.shader');data=manifest()
        self.assertEqual(materials.bsp_material_issues(record,data),[])
        self.assertEqual(materials.bsp_material_issues({},data)[0][0],'source_reference')
        self.assertEqual(materials.bsp_material_issues(record,None)[0][0],'shader_description')
        del data['shaders'][record['source_shader']]
        self.assertEqual(materials.bsp_material_issues(record,data)[0][0],'shader_description')
        data=manifest();data['bitmaps'].clear()
        self.assertEqual({s for s,_ in materials.bsp_material_issues(record,data)},{'bitmap_extraction'})
    def test_terrain_is_distinct_from_generic_unsupported_family(self):
        data=manifest();shader=next(iter(data['shaders'].values()));shader['group']='rmtr'
        self.assertEqual(materials.plan(shader)['family'],'rmtr')
        self.assertFalse(any('generic object' in d for d in materials.plan(shader)['diagnostics']))
        shader['group']='rmw '
        self.assertIn('shader_class',[s for s,_ in materials.bsp_material_issues(dict(source_shader=shader['source']),data)])

if __name__=='__main__':unittest.main()

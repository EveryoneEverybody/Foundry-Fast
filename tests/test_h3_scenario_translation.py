"""Complete-scenario identity invariants, including sparse authored masks."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment import scenario_ir
from test_h3_environment_selection import scenario, field, block


class WholeScenario(unittest.TestCase):
    def source(self):
        root = scenario()
        zones = next(e for e in root if e.get('name') == 'zone sets')
        zones[0][0].set('value', 'intro')
        next(e for e in zones[0] if e.get('name') == 'bsp zone flags').set('value', '1')
        row = deepcopy(zones[0]); row.set('index', '1'); row[0].set('value', 'all')
        next(e for e in row if e.get('name') == 'bsp zone flags').set('value', '3')
        field(row, 'hint previous zone set', ',0'); zones.append(row); zones.set('value', 'synthetic,2')
        return root

    def test_unzoned_bsp_is_decoded_without_activating_it_in_authored_all(self):
        result = scenario_ir.select_all(self.source(), 'levels/synthetic/world.scenario')
        self.assertEqual(len(result['bsps']), 3)
        self.assertEqual(result['geometry_source_bsp_mask'], 7)
        self.assertEqual(result['target_bsp_mask'], 1)
        self.assertEqual([(z['target_name'], z['target_bsp_mask']) for z in result['zone_sets']], [('intro', 1), ('all', 3)])
        self.assertEqual(result['zone_sets'][1]['hint_previous_zone_set'], 0)

    def test_sky_activation_does_not_expand_from_default_sky(self):
        root = self.source()
        sky = next(e for e in root if e.get('name') == 'skies')[0]
        next(e for e in sky if e.get('name') == 'active on bsps').set('value', '1')
        result = scenario_ir.select_all(root, 'levels/synthetic/world.scenario')
        self.assertEqual(result['skies'][0]['active_bsp_mask'], 1)
        self.assertEqual([b['target_sky_index'] for b in result['bsps']], [0, 0, 0])

    def test_sparse_remap_and_absent_member_rejection(self):
        self.assertEqual(scenario_ir.remap_mask(5, {0:1, 2:0}, 3), 3)
        for mask, mapping in [(4, {0:0}), (8, {0:0}), (-1, {0:0})]:
            with self.assertRaises(ValueError):
                scenario_ir.remap_mask(mask, mapping, 3)

    def test_repeated_flattened_type_fields_do_not_lose_palette_identity(self):
        root = self.source(); b = block(root, 'scenery', [{'type':',2', 'name':',0',
            'position':'1,2,3', 'rotation':'90,2,3', 'scale':'0'}])
        field(b[0], 'type', 'scenery', 'char enum')
        row = scenario_ir.placement(b[0], 'scenery', [dict(source_tag='a.scenery')]*3,
                                    [dict(name='door_frame')], 3, 0)
        self.assertEqual(row['source_palette_index'], 2)
        self.assertEqual(row['source_object_name'], 'door_frame')
        self.assertEqual(row['scale'], 1)
        self.assertEqual(row['position_world'], [1,2,3])
        self.assertEqual(len([r for r in row['source_records'] if r['name']=='type']), 2)
        self.assertEqual(row['native_status'], 'NOT_GENERATED')

    def test_invalid_parent_or_group_is_explicit_blocker(self):
        root=self.source(); b=block(root,'controls',[{'type':',0','name':',-1','position':'0,0,0',
            'rotation':'0,0,0','scale':'1','parent object':',7','position group':',3'}])
        row=scenario_ir.placement(b[0],'controls',[dict(source_tag='a.device_control')],[],3,1)
        self.assertEqual(row['classification'],'BLOCKING_UNKNOWN')
        self.assertEqual(len(row['source_problems']),2)


if __name__ == '__main__':
    unittest.main()

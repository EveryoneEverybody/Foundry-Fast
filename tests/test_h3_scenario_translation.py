"""Complete-scenario identity invariants, including sparse authored masks."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment import scenario_ir, authoring, semantics, native_contracts
from test_h3_environment_selection import scenario, field, block
from test_h3_environment import inputs, roots
from port_environment.model import map_collision


class WholeScenario(unittest.TestCase):
    def test_seam_front_matches_collision_winding_not_bsp_index_order(self):
        points=[[0,0,0],[1,0,0],[0,1,0]]
        seam=dict(source_index=0,vertices_world=points,triangles=[[0,1,2]],
                  owners=[dict(source_bsp_index=i) for i in [1,2]])
        bsps=[dict(source_index=i,materials=[dict(source_seam_mapping=0)],meshes=[dict(role='collision',
            vertices=[dict(position=p) for p in points],triangles=[dict(vertices=t,material=0,surface_type='seam')])])
            for i,t in [(1,[2,1,0]),(2,[0,1,2])]]
        before=deepcopy(bsps)
        self.assertEqual([r['source_bsp_index'] for r in native_contracts.seam_owner_order(seam,bsps)],[2,1])
        self.assertEqual(bsps,before)
        bsps[0]['meshes'][0]['triangles'][0]['vertices']=[0,1,2]
        with self.assertRaisesRegex(ValueError,'opposing'):native_contracts.seam_owner_order(seam,bsps)
        bsps[0]['meshes'][0]['triangles']=[]
        with self.assertRaisesRegex(ValueError,'absent'):native_contracts.seam_owner_order(seam,bsps)

    def test_no_way_portal_is_a_native_visibility_barrier(self):
        bsp=dict(source_tag='b.scenario_structure_bsp',environment_semantics=dict(authoring=dict(clusters=[{}],portals=[
            dict(source_index=0,flags={'value':8},vertices=[{'point':p} for p in ['0,0,0','1,0,0','0,1,0']],
                 **{'front cluster':0,'back cluster':-1})])))
        portals,errors=authoring.portal_plan(bsp)
        self.assertFalse(errors)
        self.assertEqual(portals[0]['portal_type'],'_connected_geometry_portal_type_no_way')

    def test_seam_uses_explicit_original_indices_and_rejects_unbounded_drift(self):
        root=ET.Element('tag',group='structure_seams',id='b')
        row=block(root,'seams',[{f'seam_id{k}':k+1 for k in range(4)}])[0]
        block(row,'original vertices',[{'original vertex':p,'final point index':i} for i,p in enumerate(['0,0,0','1,0,0','0,1,0'])])
        final=block(row,'points',[{'final point':p} for p in ['0.0001,0,0','1,0,0','0,1,0']])
        block(row,'triangles',[{f'final point{k}':f',{k}' for k in range(3)}]*2)
        bsps=[dict(source_tag=str(i),bsp_index=i,environment_semantics=dict(authoring=dict(seams=[dict(source_index=0,
            **{'seams identifier':{f'seam_id{k}':k+1 for k in range(4)},'cluster mapping':[{}],'edge mapping':[]})]))) for i in range(2)]
        result,errors=authoring.seam_plan(root,bsps)
        self.assertFalse(errors)
        self.assertEqual(result[0]['vertices_world'][0],[0,0,0])
        self.assertEqual(result[0]['source_vertex_correspondence']['rows'][0]['distance_world'],.0001)
        final[0][0].set('value','0.1,0,0')
        result,errors=authoring.seam_plan(root,bsps)
        self.assertEqual(len(errors),1)
        self.assertEqual(errors[0]['source_triangles'],[0,1])
        self.assertFalse(result[0]['triangles'])

    def test_change_color_extern_requires_the_matching_native_option(self):
        p=dict(name='primary_change_color',type='color',extern='change color primary')
        result=semantics.parameter_plan(p,{},dict(albedo='two_change_color'))
        self.assertFalse(result['still_blocking'])
        self.assertTrue(semantics.parameter_plan(p,{},dict(albedo='default'))['still_blocking'])

    def test_invalid_lighting_index_is_only_deferred_when_explicitly_requested(self):
        bsp=dict(materials=[dict(source_shader='b.shader')],environment_semantics=dict(authoring=dict(materials=[
            {'imported material index':2089878893,'properties':[]}])))
        self.assertTrue(semantics.lighting_material(bsp,0)['still_blocking'])
        result=semantics.lighting_material(bsp,0,defer_invalid_lighting=True)
        self.assertFalse(result['still_blocking'])
        self.assertEqual(result['resolution_class'],'RUNTIME_LATER')
        self.assertEqual(result['target_authoring_plan']['source_material']['imported material index'],2089878893)

    def test_structure_ladder_faces_preserve_collision_and_two_sided_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            data=inputs(roots(directory))
            bsp=data[1]
            bsp['environment_semantics']['collision_surfaces'][0]['flags']=5
            converted=map_collision(bsp,sky_index=0)
            triangle=converted['objects'][1]['triangles'][0]
            self.assertTrue(triangle['ladder'])
            self.assertTrue(triangle['two_sided'])
            self.assertEqual(triangle['vertices'],bsp['objects'][1]['triangles'][0]['vertices'])
            with self.assertRaises(ValueError):map_collision(bsp)

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

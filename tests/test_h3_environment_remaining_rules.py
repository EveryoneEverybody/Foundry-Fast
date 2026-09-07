"""Synthetic proof obligations for unified glass, angular emission and seam state."""
from copy import deepcopy
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment import authoring, breakable_geometry as glass, emissive, seam_states, semantics


def glass_fixture():
    points=[[0.,0.,0.],[1.,0.,0.],[1.,1.,0.],[0.,1.,0.]]
    vertices=[dict(position=list(p),normal=[0.,0.,float(sign)],uvs=[p[:2]],weights=[],color=[1.,1.,1.])
              for sign in (1,-1) for p in points]
    render=dict(id=42,vertices=vertices,triangles=[dict(vertices=t,material=0) for t in
        ([0,1,2],[6,5,4],[0,2,3],[7,6,4])])
    surfaces=[dict(source_surface=i,flags=9,plane=0 if i==0 else -0x8000,material=1,
        ring=dict(decoded_vertices=ring,source_edges=list(range(4)),source_vertices=ring))
        for i,ring in enumerate(([0,1,2,3],[3,2,1,0]))]
    collision=dict(vertices=[dict(position=p) for p in points],source_surfaces=surfaces,
        planes_source=[dict(plane=dict(values=[0.,0.,1.,0.]))])
    materials=[{}, {'render method':dict(path='synthetic/glass',extension='shader')}]
    return render,collision,{0:'synthetic/glass.shader'},materials


def light_fixture():
    return {'emissive power':'0.8','emissive focus':'0','emissive quality':'1','emissive color':'1,0.5,0.2',
            'frustum blend':'0.5','frustum falloff angle':'25','frustum cutoffoff angle':'45',
            'attenuation falloff':'1','attenuation cutoff':'2','flags':'1'}


def seam_fixture():
    owner=dict(source_bsp_index=1,source_bsp='synthetic/b.scenario_structure_bsp',
               cluster_mapping=[],edge_mapping=[])
    seam=dict(source_index=0,identifier=[1,2,3,4],owners=[owner],
              vertices_world=[[0.,0.,0.],[1.,0.,0.],[1.,1.,0.],[0.,1.,0.]],triangles=[[0,1,2],[0,2,3]])
    collision=dict(id=99,vertices=[dict(position=[v*100 for v in p]) for p in seam['vertices_world']],
        triangles=[dict(vertices=t,material=0) for t in seam['triangles']])
    bsp=dict(source_tag=owner['source_bsp'],bsp_index=1,objects=[collision],
        environment_semantics=dict(collision_object=99,collision_surfaces=[dict(source_surface=0,material=0,flags=0,
            triangle_start=0,triangle_count=2)],authoring=dict(collision_materials=[{'seam mapping index':0}])))
    context=dict(neighbor_evidence=[dict(source_seam_index=0,identifier=seam['identifier'],selected_owner=owner,
        inactive_neighbor=dict(source_bsp_index=2,source_bsp='synthetic/c.scenario_structure_bsp'))],
        source_zone_sets=[dict(name='first',bsp_mask=3),dict(name='next',bsp_mask=6),dict(name='alone',bsp_mask=2)])
    plan=dict(seams=[seam],selection=dict(bsps=[dict(source_index=i) for i in (0,1)]),seam_source_context=context)
    record=authoring.issue('synthetic/world.structure_seams','seams[].selected BSP owners',[0],'unpaired')
    return record,plan,[dict(bsp_index=0,source_tag='synthetic/a.scenario_structure_bsp'),bsp]


class UnifiedBreakableGeometry(unittest.TestCase):
    def prove(self,fixture=None):
        return glass.prove(*(fixture or glass_fixture()),units='ass_100_per_world_unit')

    def test_complete_coverage_preserves_attributes_and_deterministic_face_ids(self):
        f=glass_fixture();before=deepcopy(f);p=self.prove(f)
        self.assertEqual(p,self.prove(f));self.assertEqual(f,before)
        self.assertEqual(p['unified_triangle_count'],2)
        self.assertEqual(p['collision_surface_count'],2)
        self.assertEqual(p['unique_collision_polygon_count'],1)
        self.assertEqual(p['retained_render_triangles'],[0,2])
        self.assertEqual(p['suppressed_opposite_render_triangles'],[1,3])
        self.assertTrue(all(r['boundary_edges_match'] for r in p['rings']))

    def test_material_identity_not_slot_number_establishes_correspondence(self):
        f=glass_fixture();self.assertFalse(f[0]['triangles'][0]['material']==f[1]['source_surfaces'][0]['material'])
        self.prove(f)
        f[2][0]='synthetic/different.shader'
        with self.assertRaisesRegex(ValueError,'shader identity'):self.prove(f)

    def test_attribute_mismatch_missing_side_and_extra_geometry_fail_closed(self):
        for kind in ('uv','normal','missing','extra','duplicate'):
            with self.subTest(kind=kind):
                f=deepcopy(glass_fixture());render=f[0]
                if kind=='uv':render['vertices'][4]['uvs']=[[.9,.9]]
                if kind=='normal':render['vertices'][4]['normal']=[0,0,1]
                if kind=='missing':render['triangles'].pop()
                if kind in ('extra','duplicate'):render['triangles'].append(deepcopy(render['triangles'][0]))
                with self.assertRaises(ValueError):self.prove(f)

    def test_roundoff_match_is_bounded_and_never_welds_ambiguous_vertices(self):
        f=deepcopy(glass_fixture());f[1]['vertices'][0]['position'][0]=1e-7
        self.assertGreater(self.prove(f)['maximum_vertex_error_ass_units'],0)
        f[0]['vertices'].append(dict(position=[2e-7,0,0],normal=[0,0,1],uvs=[],weights=[],color=[]))
        with self.assertRaisesRegex(ValueError,'render vertices'):self.prove(f)

    def test_bad_planes_boundaries_flags_and_uncovered_collision_fail(self):
        for kind in ('plane','nonplanar','boundary','flags','ring_duplicate'):
            with self.subTest(kind=kind):
                f=deepcopy(glass_fixture());c=f[1]
                if kind=='plane':c['planes_source'][0]['plane']['values'][3]=1.
                if kind=='nonplanar':c['vertices'][3]['position'][2]=.5
                if kind=='boundary':c['source_surfaces'][0]['ring']['decoded_vertices']=[0,2,1,3]
                if kind=='flags':c['source_surfaces'][0]['flags']=1
                if kind=='ring_duplicate':c['source_surfaces'].append(deepcopy(c['source_surfaces'][0]))
                with self.assertRaises(ValueError):self.prove(f)

    def test_plan_requires_validated_placement_object_and_whole_definition(self):
        render,collision,materials,collision_materials=glass_fixture()
        definition={'mesh index':17,'collision_mesh':collision}
        bsp=dict(units='ass_100_per_world_unit',objects=[render],materials=[dict(source_shader=materials[0])],
            environment_semantics=dict(authoring=dict(definitions=[definition],collision_materials=collision_materials)))
        placements=[dict(source_index=i,source_definition=0,render_object=42,collision_definition=0,matrix=[i]) for i in (5,7)]
        ip=dict(placements=placements);r=dict(source_definition=0,affected=[0,1],affected_instances=[5,7])
        p=glass.plan(bsp,ip,r)
        self.assertEqual(p['source_render_mesh'],17);self.assertEqual(p['source_render_object'],42)
        self.assertEqual(p['target']['face_mode'],'breakable');self.assertFalse(p['target']['collision_proxy'])
        self.assertEqual(p['placements'],placements)
        placements[0]['render_object']=7
        with self.assertRaisesRegex(ValueError,'linkage'):glass.plan(bsp,ip,r)
        placements[0]['render_object']=42;r['affected'].pop()
        with self.assertRaisesRegex(ValueError,'partition'):glass.plan(bsp,ip,r)


class DirectionalEmission(unittest.TestCase):
    def test_source_power_color_and_distance_survive_angular_approximation(self):
        source=light_fixture();before=deepcopy(source);p=emissive.plan(source);t=p['target']
        self.assertEqual(source,before);self.assertEqual(p,emissive.plan(source))
        self.assertEqual(t['emissive_power'],.8);self.assertEqual(t['emissive_color'],[1,.5,.2])
        self.assertEqual((t['attenuation_falloff_world'],t['attenuation_cutoff_world']),(1,2))
        self.assertGreater(t['native_emissive_focus'],0);self.assertLess(t['native_emissive_focus'],1)
        self.assertAlmostEqual(1-math.degrees(t['foundry_emissive_spread_radians'])/180,t['native_emissive_focus'])
        self.assertAlmostEqual(math.radians(180*(1-t['native_emissive_focus'])),t['foundry_emissive_spread_radians'])
        self.assertTrue(p['fidelity_loss']);self.assertTrue(p['assumptions'])

    def test_zero_frustum_blend_retains_basic_focus_and_full_blend_uses_cone(self):
        source=light_fixture();source['frustum blend']='0';source['emissive focus']='0.3'
        self.assertAlmostEqual(emissive.plan(source)['target']['native_emissive_focus'],.3)
        source.update({'frustum blend':'1','frustum falloff angle':'30','frustum cutoffoff angle':'30'})
        self.assertAlmostEqual(math.degrees(emissive.plan(source)['target']['foundry_emissive_spread_radians']),60)

    def test_bad_angular_flags_power_or_distance_inputs_remain_blocking(self):
        for key,value in [('flags','2'),('emissive power','0'),('frustum blend','1.1'),('frustum falloff angle','60'),
                          ('frustum cutoffoff angle','100'),('attenuation falloff','3'),('emissive focus','nan')]:
            with self.subTest(key=key):
                s=light_fixture();s[key]=value
                with self.assertRaises(ValueError):emissive.plan(s)

    def test_native_plan_joins_lighting_row_to_material_identity(self):
        source=light_fixture();r=authoring.issue('synthetic/b.lightinfo','material info',[7],'angular',source_value=source)
        plan=dict(lighting_by_bsp=[dict(source_tag='synthetic/b.lightinfo',source_bsp_index=1)],
            bsps=[dict(source_index=1,source_tag='synthetic/b.bsp',materials=[dict(source_shader='synthetic/lamp.shader',
                source_lighting_index=7,lighting=source)])])
        result=semantics.resolve_record(r,plan,[],{})
        self.assertFalse(result['still_blocking'])
        self.assertEqual(result['target_authoring_plan']['material_bindings'][0]['source_shader'],'synthetic/lamp.shader')
        plan['bsps'][0]['materials'][0]['source_lighting_index']=8
        self.assertTrue(semantics.resolve_record(r,plan,[],{})['still_blocking'])


class InactiveSeam(unittest.TestCase):
    def test_neighbor_probe_uses_source_zone_masks_and_rejects_repeated_id_alone(self):
        from test_h3_environment_selection import field,block
        r,e,bsps=seam_fixture();seam=e['seams'][0]
        seam['owners'][0]['cluster_mapping']=[{'cluster center':{'values':[.5,.5,0.]}}]
        scenario=ET.Element('tag',group='scenario',id='synthetic/world')
        block(scenario,'structure bsps',[{'structure bsp':f'synthetic/{i},sbsp'} for i in range(4)])
        block(scenario,'zone sets',[{'name':'selected','bsp zone flags':3},{'name':'next','bsp zone flags':6},
                                   {'name':'later','bsp zone flags':12}])
        calls=[]
        def metadata(i,source):
            calls.append((i,source))
            root=ET.Element('tag',group='scenario_structure_bsp',id=f'synthetic/{i}')
            rows=block(root,'seam identifiers',[{f'seam_id{k}':v for k,v in enumerate(seam['identifier'])}])
            row=rows[0];block(row,'edge mapping',[{'structure edge index':i}])
            block(row,'cluster mapping',[{'cluster_index':2,'cluster center':center}])
            return root,dict(source_sha256='a'*64,xml='metadata.xml',xml_sha256='b'*64)
        with patch.object(authoring,'seam_plan',return_value=([seam],[])):
            center='0.5,0.5,0'
            result=seam_states.discover_neighbors(scenario,bsps,None,metadata)
            self.assertEqual(calls,[(2,'synthetic/2.scenario_structure_bsp')])
            self.assertEqual(result['neighbor_evidence'][0]['inactive_neighbor']['source_bsp_index'],2)
            self.assertEqual(result['selected_indices'],[0,1])
            relationship=result['scenario_global_relationships'][0]
            self.assertEqual([o['source_bsp_index'] for o in relationship['owners']],[1,2])
            self.assertEqual([s['seam_active'] for s in relationship['source_zone_states']],[False,True,False])
            self.assertEqual(relationship['selected_owner_indices'],[1])
            calls.clear();center='50,50,0'
            result=seam_states.discover_neighbors(scenario,bsps,None,metadata)
            self.assertEqual(result['neighbor_evidence'],[])
            self.assertEqual(result['unresolved_neighbors'],[0])
            self.assertEqual(result['scenario_global_relationships'],[])

    def test_owner_pair_activation_preserves_existing_collision_without_added_bsp(self):
        r,e,b=seam_fixture();before=deepcopy((r,e,b));p=seam_states.plan(r,e,b)
        self.assertEqual((r,e,b),before);self.assertEqual(p,seam_states.plan(r,e,b))
        self.assertFalse(p['selected_seam_active']);self.assertTrue(p['source_collision_extant'])
        self.assertEqual([s['seam_active'] for s in p['source_zone_states']],[False,True,False])
        self.assertFalse(p['target']['added_geometry']);self.assertFalse(p['target']['seam_connector'])
        self.assertEqual(p['target']['face_mode'],'collision_only')
        self.assertEqual(p['collision_correspondence']['source_collision_triangle_indices'],[0,1])
        self.assertEqual(e['selection']['bsps'],[dict(source_index=0),dict(source_index=1)])

    def test_repeated_identifier_wrong_geometry_missing_neighbor_or_decode_fails(self):
        for kind in ('index','geometry','missing_neighbor','incomplete','paired'):
            with self.subTest(kind=kind):
                r,e,b=deepcopy(seam_fixture())
                if kind=='index':e['seam_source_context']['neighbor_evidence'][0]['source_seam_index']=1
                if kind=='geometry':b[1]['objects'][0]['vertices'][0]['position'][0]+=10
                if kind=='missing_neighbor':e['seam_source_context']={}
                if kind=='incomplete':b.pop(0)
                if kind=='paired':e['seams'][0]['owners'].append(dict(source_bsp_index=0))
                self.assertTrue(semantics.resolve_record(r,e,b,{})['still_blocking'])

    def test_unmapped_reach_seam_is_not_a_valid_collision_replacement(self):
        p=seam_states.plan(*seam_fixture())
        self.assertEqual(p['target']['face_type'],'normal')
        self.assertIn('IsSeam',p['target']['reach_unmapped_seam_caveat'])

    def test_global_ownership_survives_zone_sets_with_both_one_or_neither_owner(self):
        r,e,b=seam_fixture()
        e['seam_source_context']['source_zone_sets'].append(dict(name='neither_owner',bsp_mask=1))
        before=deepcopy((r,e,b));p=seam_states.plan(r,e,b);global_plan=p['scenario_global_authoring']
        self.assertEqual((r,e,b),before)
        self.assertEqual(global_plan['ownership_scope'],'SCENARIO_GLOBAL')
        self.assertEqual(global_plan['semantic_class'],'NATIVE_DIRECT')
        self.assertTrue(global_plan['preserve_global_seam'])
        self.assertEqual([o['source_bsp_index'] for o in global_plan['owners']],[1,2])
        self.assertEqual([s['seam_active'] for s in global_plan['source_zone_states']],[False,True,False,False])
        self.assertEqual(global_plan['selected_build_bsp_indices'],[0,1])
        self.assertEqual(global_plan['owner_bsps_outside_selected_build'],[2])
        self.assertIn('target scenario',global_plan['writer_precondition'])
        self.assertIn('commented out',global_plan['imported_helper_limit'])
        self.assertFalse(p['target']['added_geometry'])
        self.assertEqual(semantics.resolve_record(r,e,b,{})['resolution_class'],'NATIVE_TRANSFORM')


if __name__=='__main__':unittest.main()

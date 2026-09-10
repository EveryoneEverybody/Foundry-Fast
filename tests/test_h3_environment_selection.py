"""Synthetic campaign contracts; no proprietary world/resource fixtures."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment import fixtures, model, authoring
from port_environment.cli import finish_stage_timings
from port_environment.validation import lighting_count_errors
from port_environment.paths import OutputPaths
from port_environment.selection import select, SCENARIO_FIELDS
from test_h3_environment import inputs, roots


def field(node,name,value,type='string id'):
    return ET.SubElement(node,'field',name=name,value=str(value),type=type)


def block(node,name,rows):
    b=ET.SubElement(node,'block',name=name,value='synthetic,'+str(len(rows)))
    for i,values in enumerate(rows):
        row=ET.SubElement(b,'element',index=str(i))
        for name,value in values.items(): field(row,name,value)
    return b


def scenario(mask=5):
    root=ET.Element('tag',group='scenario',id='levels/synthetic/world')
    field(root,'type','solo')
    block(root,'structure bsps',[{'structure bsp':f'levels/synthetic/b{i},sbsp','structure design':',NULL',
        'structure lighting_info':f'levels/synthetic/b{i},stli','default sky':',0'} for i in range(3)])
    block(root,'zone sets',[{'name':'selected','bsp zone flags':mask}])
    block(root,'skies',[{'sky':'levels/synthetic/sky,scen','active on bsps':7}])
    block(root,'cutscene flags',[{'name':'authored_start','position':'1,2,3','facing':'90,0'}])
    return root


class CampaignSelection(unittest.TestCase):
    def test_authored_mask_selects_every_required_bsp_and_remaps_indices(self):
        result=select(scenario(),'levels/synthetic/world.scenario','selected','authored_start')
        self.assertEqual(result['source_bsp_mask'],5)
        self.assertEqual(result['target_bsp_mask'],3)
        self.assertEqual([(r['source_index'],r['target_index']) for r in result['bsps']],[(0,0),(2,1)])
        self.assertEqual(result['skies'][0]['active_bsp_mask'],3)
        self.assertEqual(result['spawn']['position_world'],[1,2,3])
        self.assertEqual(result['spawn']['facing_degrees'],90)

    def test_absent_ambiguous_empty_and_out_of_range_masks_fail(self):
        for mask in (0,8,-1):
            with self.subTest(mask=mask),self.assertRaises(ValueError):select(scenario(mask),'levels/synthetic/world.scenario','selected')
        for name in (None,'missing'):
            with self.assertRaises(ValueError):select(scenario(),'levels/synthetic/world.scenario',name)
        root=scenario();zones=next(e for e in root if e.get('name')=='zone sets')
        zones.append(deepcopy(zones[0]));zones[1].set('index','1');zones.set('value','synthetic,2')
        with self.assertRaises(ValueError):select(root,'levels/synthetic/world.scenario','selected')

    def test_nested_namespace_requires_explicit_campaign_scope_and_preserves_proof(self):
        with tempfile.TemporaryDirectory() as d:
            base=roots(d)
            result=OutputPaths(base.h3,base.reach,'levels/h3_port/synthetic/environment',allow_nested=True)
            self.assertTrue(result.scenario.endswith('/environment/environment'))
            with self.assertRaises(ValueError):OutputPaths(base.h3,base.reach,'levels/h3_port/proof_box/child',allow_nested=True)

    def test_campaign_mapping_catalog_does_not_relabel_plans_as_native_acceptance(self):
        catalog=json.loads(Path(model.__file__).with_name('mappings.json').read_text())
        proof={r['id'] for r in catalog['rules']}
        self.assertTrue(set(catalog['campaign_shared_rule_ids'])<=proof)
        for row in catalog['campaign_rules']:
            self.assertNotIn(row['id'],proof)
            self.assertEqual(row['classification'],'PLANNED_ONLY')
            self.assertTrue(row['evidence'] and row['confidence'])

    def test_streamed_tool_reader_ignores_only_display_labels_and_unselected_payload(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'source.xml'
            p.write_bytes(b'<tag group="scenario" id="example">\n'
                b'    <block name="cutscene flags" value="flags,1">\n'
                b'        <element index="0" name=" <unknown>">\n'
                b'            <field name="name" value="actual_authored_name"/>\n'
                b'        </element>\n    </block>\n'
                b'    <block name="compiled data" value="blob,1">\n malformed <blob>\n    </block>\n</tag>')
            r=fixtures.read_authoring(p,{'cutscene flags'})
            self.assertEqual(fixtures.field(fixtures.block(r,'cutscene flags')[0],'name'),'actual_authored_name')
            p.write_bytes(p.read_bytes().replace(b'actual_authored_name',b'<invalid_field>'))
            with self.assertRaises(ET.ParseError):fixtures.read_authoring(p,{'cutscene flags'})

    def test_design_geometry_is_reorganized_without_mopp_copy(self):
        r=ET.Element('tag',group='structure_design',id='levels/synthetic/design')
        b=block(r,'soft ceilings block',[{'name':'boundary','type':'acceleration'}])
        block(b[0],'soft ceiling triangles',[{'vertex0':'0,0,0','vertex1':'1,0,0','vertex2':'0,1,0'}])
        block(r,'soft ceiling mopp code block',[{'mopp data':'never copied'}])
        plan,errors=authoring.design_plan(r,'levels/synthetic/design.structure_design',scenario())
        self.assertFalse(errors)
        self.assertEqual(plan['source_triangles'],1)
        self.assertEqual(plan['meshes'][0]['boundary_surface_type'],'SOFT_CEILING')
        self.assertNotIn('mopp data',str(plan))
        block(r,'water groups block',[{'unsupported':'present'}])
        self.assertTrue(authoring.design_plan(r,'levels/synthetic/design.structure_design',scenario())[1])

    def test_static_lights_have_explicit_units_and_source_indices(self):
        r=ET.Element('tag',group='scenario_structure_lighting_info')
        block(r,'generic light definitions',[{'type':'spot','shape':'rectangle','flags':2,'color':'1,0.5,0.2',
            'intensity':3,'hotspot size':0.5,'hotspot falloff size':1,'near attenuation bounds':'0,0.5',
            'far attenuation bounds':'2,5','aspect':2}])
        block(r,'generic light instances',[{'definition index':0,'origin':'1,2,3','forward':'0,1,0','up':'0,0,1'}])
        block(r,'material info',[])
        plan,errors=authoring.static_lighting(r,'synthetic.scenario_structure_lighting_info')
        self.assertFalse(errors)
        self.assertAlmostEqual(plan['definitions'][0]['hotspot_size'],28.6478897565)
        self.assertEqual(plan['instances'][0]['origin'],[1,2,3])
        self.assertEqual(plan['counts']['source_generic_static_lights'],1)

    def test_light_volume_fields_and_opaque_functions_are_evidence_not_merged_or_executed(self):
        root=scenario()
        volumes=block(root,'light volumes',[{'type':',0'}])
        field(volumes[0],'type','spot','short enum')
        block(root,'light volumes palette',[{'name':'levels/synthetic/lamp,ligh'}])
        tag=ET.Element('tag',group='light',id='levels/synthetic/lamp')
        field(tag,'data','do not execute this source payload','data')
        selection=select(root,'levels/synthetic/world.scenario','selected')
        plan,errors=authoring.scenario_light_plan(root,selection,{'levels/synthetic/lamp.light':tag})
        self.assertEqual([f['attributes']['value'] for f in plan['placements'][0]['fields']],[',0','spot'])
        self.assertNotIn('do not execute',str(plan))
        self.assertIn('opaque_function_data',plan['palette'][0]['fields'][0])
        self.assertEqual(errors[0]['affected'],[0])

    def test_collision_only_instance_is_retained_and_negative_material_is_not_sky(self):
        row={'source_index':0,'name':'stairs','instance definition':0,'flags':{'value':8},
             'position':{'values':[1,2,3]},'forward':{'values':[1,0,0]},'left':{'values':[0,1,0]},
             'up':{'values':[0,0,1]},'scale':{'values':[2]}}
        a={'version':1,'instances':[row],'definitions':[{'mesh index':0,'collision_mesh':{
            'source_surfaces':[{'flags':{'value':5},'material':-1,'source_surface':4}]}}],
           'render_meshes':[{'parts':[]}],'weather':[]}
        b={'source_tag':'synthetic.scenario_structure_bsp','instances':[],'environment_semantics':{'authoring':a}}
        plan,errors=authoring.instance_plan(b)
        self.assertFalse(errors);self.assertEqual(plan['collision_only_count'],1)
        self.assertEqual(plan['placements'][0]['matrix'][0],[2,0,0,100])
        problems=authoring.audit_bsp(b)
        self.assertEqual(len(problems),2)
        self.assertEqual(problems[0]['affected_instances'],[0])
        self.assertEqual(problems[0]['affected'],[4])

    def test_portal_unknown_bits_report_exact_source_and_keep_cluster_adjacency(self):
        p={'source_index':2,'flags':{'value':128},'front cluster':0,'back cluster':1,
           'vertices':[{'point':{'values':v}} for v in ([0,0,0],[1,0,0],[0,1,0])]}
        b={'source_tag':'synthetic.scenario_structure_bsp','environment_semantics':{'authoring':{'portals':[p],'clusters':[{},{}]}}}
        plan,errors=authoring.portal_plan(b)
        self.assertEqual(plan[0]['source_back_cluster'],1)
        self.assertEqual(errors[0]['source_field'],'cluster portals[].flags')
        self.assertEqual(errors[0]['affected'],[2])

    def test_shader_cache_identity_deduplicates_shared_bsp_materials(self):
        with tempfile.TemporaryDirectory() as d:
            args=inputs(roots(d)); sources=model.used_shaders([args[1],deepcopy(args[1])],[args[2]])
            self.assertEqual(len(sources),2)
            self.assertEqual(sources,sorted(set(sources)))

    def test_unused_definitions_do_not_expand_the_shader_dependency_set(self):
        with tempfile.TemporaryDirectory() as d:
            args=inputs(roots(d));bsp=args[1]
            before=model.used_shaders([bsp],[args[2]])
            slot=len(bsp['materials']);bsp['materials'].append(dict(source_shader='unused/synthetic.shader'))
            unused=deepcopy(bsp['objects'][0]);unused['id']=len(bsp['objects']);unused['triangles'][0]['material']=slot
            bsp['objects'].append(unused)
            self.assertEqual(before,model.used_shaders([bsp],[args[2]]))
            placement=deepcopy(bsp['instances'][1]);placement.update(id=3,object=unused['id'],name='used instance')
            bsp['instances'].append(placement)
            self.assertIn('unused/synthetic.shader',model.used_shaders([bsp],[args[2]]))

    def test_pre_faux_counts_reject_missing_and_black_lighting(self):
        source=dict(sky_samples=2,light_definitions=1,light_instances=3,emissive_rows=1)
        native=dict(source,sky_energy=4.0)
        self.assertFalse(lighting_count_errors(source,native))
        for key in ('sky_samples','light_definitions','light_instances','emissive_rows','sky_energy'):
            with self.subTest(key=key):
                self.assertTrue(lighting_count_errors(source,dict(native,**{key:0})))

    def test_native_tool_journal_finalization_and_lighting_readback(self):
        # Native Tool records deliberately have no CLI stage key.
        tool=dict(command=['tool.exe','import','generated.sidecar.xml'],status='ACCEPTED',exit_code=0,seconds=2)
        faux=dict(command=['tool.exe','faux_farm_begin','generated'],status='ACCEPTED',exit_code=0,seconds=3)
        report=dict(tool_invocations=[dict(stage='h3-scenario-decode',seconds=1),tool,faux],stage_timings={},
            lighting_inputs={},source_material_helper_timings=dict(shader_metadata_exclusive_seconds=.2,bitmap_extraction_seconds=.5),
            worker=dict(tool_invocations=[tool,faux],lighting_input_readback=dict(status='NATIVE_COUNTS_VERIFIED_BEFORE_FAUX',
                native=dict(sky_samples=200,light_definitions=0,light_instances=0,emissive_rows=0))))
        finish_stage_timings(report)
        self.assertEqual(report['stage_timings']['Tool']['seconds'],2)
        self.assertEqual(report['stage_timings']['Faux']['seconds'],3)
        self.assertEqual(report['stage_timings']['bitmaps']['seconds'],.5)
        self.assertEqual(report['lighting_inputs']['Reach_sky_samples_written'],200)

    def test_repeated_seam_identifiers_do_not_fabricate_adjacency(self):
        r=ET.Element('tag',group='structure_seams',id='levels/synthetic/world')
        rows=block(r,'seams',[{f'seam_id{k}':k+1 for k in range(4)} for _ in range(2)])
        for row in rows:
            block(row,'original vertices',[{'original vertex':p,'final point index':i}
                  for i,p in enumerate(('0,0,0','1,0,0','0,1,0'))])
            block(row,'points',[{'final point':p} for p in ('0,0,0','1,0,0','0,1,0')])
            block(row,'triangles',[{f'final point{k}':f',{k}' for k in range(3)}])
        def bsp(i,active):
            return dict(source_tag=f'b{i}.scenario_structure_bsp',bsp_index=i,environment_semantics=dict(authoring=dict(seams=[
                dict(source_index=j,**{'seams identifier':{f'seam_id{k}':k+1 for k in range(4)},
                                      'cluster mapping':[{'cluster_index':0}] if j in active else [],'edge mapping':[]})
                for j in range(2)])))
        plan,errors=authoring.seam_plan(r,[bsp(0,{0}),bsp(1,{0,1})])
        self.assertEqual([len(p['owners']) for p in plan],[2,1])
        self.assertEqual(len(errors),1)
        self.assertEqual(errors[0]['affected'],[1])

    def test_full_multi_bsp_plan_preserves_separate_targets_and_shared_shader_cache(self):
        with tempfile.TemporaryDirectory() as d:
            paths=roots(d);args=inputs(paths)
            root=scenario();block(root,'player starting locations',[]);block(root,'player starting profile',[])
            sr=fixtures.block(root,'skies')[0]
            next(e for e in sr if e.get('name')=='sky').set('value',args[2]['source_tag'].rsplit('.',1)[0]+',scen')
            sel=select(root,'levels/synthetic/world.scenario','selected','authored_start')
            scene=dict(source_tag=sel['source_scenario'],game='halo3_mcc')
            bsps=[];lights={}
            for row in sel['bsps']:
                b=deepcopy(args[1]);b.update(source_tag=row['source_tag'],bsp_index=row['source_index'])
                b['environment_semantics']['authoring']=dict(version=1,instances=[],definitions=[],render_meshes=[],
                    portals=[],clusters=[{}],weather=[],materials=[{'imported material index':0}],
                    collision_materials=[{}],seams=[])
                bsps.append(b);lights[row['lighting_info']]=args[5]
            for source in [sel['source_scenario'],*(r['source_tag'] for r in sel['bsps']),*lights]:
                f=paths.h3_tags/source;f.parent.mkdir(parents=True,exist_ok=True);f.write_text('synthetic source')
            sky=args[2]['source_tag']
            p=model.construct(paths,scene,bsps,[args[2]],args[3],root,lights,{sky:args[6]},{sky:args[7]},selection=sel)
            self.assertEqual([b['source_index'] for b in p['bsps']],[0,2])
            self.assertEqual(len({b['destination'] for b in p['bsps']}),2)
            self.assertEqual(len(p['materials']),2)
            self.assertEqual(p['scenario']['active_bsp_mask'],3)
            self.assertEqual(p['scenario']['spawn']['position_world'],[1,2,3])
            self.assertFalse(p['unsupported'])


if __name__=='__main__':unittest.main()

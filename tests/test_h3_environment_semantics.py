"""Source-rule tests contain synthetic authoring records, never proprietary assets."""
from copy import deepcopy
import json
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment import semantics as s, authoring, model
from test_h3_environment import inputs, roots
import tempfile


def function(kind=1, channel='value', value=0.5, flags=36):
    data = bytearray(32); data[:4] = bytes([kind, flags, 0, 0]); struct.pack_into('<f', data, 4, value)
    return dict(function_hex=data.hex(), channel=channel, input='', range='', period=1.0)


def shader(categories=None, parameters=None, group='rmsh'):
    return dict(source='synthetic/material.shader', status='resolved_snapshot', group=group,
        categories=[dict(category=k,option=v) for k,v in (categories or {}).items()],
        parameters=parameters or [], authored_parameters=[], material_names=['stone','soil','grass','sand'])


def texture(name):
    return dict(name=name, type='bitmap', bitmap='synthetic/'+name+'#0', transform=[2.,3.,0.25,0.5],
                sampler=dict(address_x='wrap',address_y='clamp'), has_functions=False)


def collision(material=-1, flags=0):
    return dict(collision_surfaces=[dict(material=material, flags=flags, source_surface=0)],
        render_correspondence=[dict(structure_surface_to_triangle_mapping_count=0)],
        rings=[dict(source_ring=dict(source_edges=[0,1,2],source_vertices=[0,1,2]),
                    positions=[[0,0,0],[1,0,0],[0,1,0]])])


def diagnostic(index, field='parameters[].functions/extern'):
    return authoring.issue(f'synthetic/{index}.shader',field,['parameter'], 'Initial unsupported source record')


class MaterialRules(unittest.TestCase):
    def test_constant_alpha_is_native_and_preserves_cutout_value(self):
        p=dict(name='alpha_test_threshold',type='real',value=0.5,has_functions=True)
        result=s.parameter_plan(p,dict(functions=[function(channel='alpha')]),dict(alpha_test='simple'))
        self.assertEqual(result['resolution_class'],'NATIVE_DIRECT')
        self.assertEqual(result['target_authoring_plan']['target_value'],0.5)
        self.assertEqual(result['target_authoring_plan']['channels'][0]['semantic_rule_id'],'material.constant')

    def test_all_authored_constant_channels_are_preserved(self):
        for channel in ('value','color','alpha','scale uniform','scale x','scale y','translation x','translation y'):
            with self.subTest(channel=channel):
                p=texture('base_map') if 'scale' in channel or 'translation' in channel else dict(name='color',type='color',value=[.1,.2,.3,.4])
                p['has_functions']=True
                result=s.parameter_plan(p,dict(functions=[function(channel=channel)]),dict(alpha_test='simple'))
                self.assertFalse(result['still_blocking'])
                self.assertEqual(result['resolution_class'],'NATIVE_DIRECT')

    def test_cosmetic_uv_freezes_deterministically(self):
        p=texture('detail_map'); p['has_functions']=True
        authored=dict(functions=[function(2,'translation x')])
        before=deepcopy((p,authored))
        first=s.parameter_plan(p,authored,dict(alpha_test='none',blend_mode='alpha_blend'))
        self.assertEqual(first,s.parameter_plan(p,authored,dict(alpha_test='none',blend_mode='alpha_blend')))
        self.assertEqual(first['resolution_class'],'STATICIZED_MVP')
        self.assertEqual(first['target_authoring_plan']['target_value'],p['transform'])
        self.assertEqual((p,authored),before)

    def test_unsafe_opacity_visibility_cutout_or_unknown_curve_stays_blocking(self):
        for name in ('opacity','visibility','dissolve','alpha_test_threshold'):
            with self.subTest(name=name):
                p=dict(name=name,type='real',value=1.,has_functions=True)
                self.assertTrue(s.parameter_plan(p,dict(functions=[function(3)]),{})['still_blocking'])
        for name in ('alpha_test_map','base_map'):
            p=texture(name);p['has_functions']=True
            self.assertTrue(s.parameter_plan(p,dict(functions=[function(2,'translation x')]),dict(alpha_test='simple'))['still_blocking'])
        p=texture('detail_map');p['has_functions']=True
        self.assertTrue(s.parameter_plan(p,dict(functions=[function(9,'translation x')]),{})['still_blocking'])

    def test_named_input_and_missing_function_bytes_fail(self):
        p=texture('detail_map');p['has_functions']=True
        f=function(2,'translation x');f['input']='mission_state'
        self.assertTrue(s.parameter_plan(p,dict(functions=[f]),{})['still_blocking'])
        self.assertTrue(s.parameter_plan(p,dict(functions=[]),{})['still_blocking'])

    def test_required_emission_cannot_freeze_to_zero(self):
        p=dict(name='self_illum_intensity',type='real',value=0.,has_functions=True)
        f=dict(functions=[function(3)])
        self.assertTrue(s.parameter_plan(p,f,{},baked_emission_preserved=True,required_bake_emission=True)['still_blocking'])
        self.assertTrue(s.parameter_plan(p,f,{})['still_blocking'])
        self.assertFalse(s.parameter_plan(p,f,{},baked_emission_preserved=True)['still_blocking'])
        p['value']=1.
        self.assertFalse(s.parameter_plan(p,f,{},baked_emission_preserved=True,required_bake_emission=True)['still_blocking'])

    def test_native_externs_and_wind_rest_are_distinct(self):
        p=dict(name='dynamic_environment_map_0',type='bitmap',extern='dynamic environment map 1')
        self.assertEqual(s.parameter_plan(p,{},dict(environment_mapping='dynamic'))['resolution_class'],'NATIVE_REBUILD')
        self.assertTrue(s.parameter_plan(p,{},dict(environment_mapping='none'))['still_blocking'])
        for extern in ('cook torrance cc0236','cook torrance dd0236','cook torrance c78d78'):
            self.assertEqual(s.parameter_plan(dict(name='lookup',extern=extern),{},{})['resolution_class'],'NATIVE_TRANSFORM')
        self.assertEqual(s.parameter_plan(dict(name='g_tree_animation_coeff',extern='tree animation timer'),{},{})['resolution_class'],'STATICIZED_MVP')
        self.assertTrue(s.parameter_plan(dict(name='hidden',extern='mission visibility'),{},{})['still_blocking'])

    def test_nonopaque_pass_composes_shadow_blend_cutout_and_lightmap(self):
        cases=[(3,'opaque','simple'),(4,'opaque','simple'),(4,'alpha_blend','none'),(4,'additive','none'),(5,'opaque','none')]
        for kind,blend,alpha in cases:
            with self.subTest(kind=kind,blend=blend,alpha=alpha):
                row=s.render_part({'part type':kind,'part flags':2},shader(dict(blend_mode=blend,alpha_test=alpha)))
                self.assertFalse(row['still_blocking'])
                p=row['target_authoring_plan']
                self.assertEqual((p['blend_mode'],p['alpha_test']),(blend,alpha))
                self.assertEqual(p['no_shadow'],kind==3)
                self.assertEqual(p['face_mode']=='lightmap_only',kind==5)
                self.assertTrue(p['lightmap_ignore'])
        for part in ({'part type':6,'part flags':0},{'part type':4,'part flags':4}):
            self.assertTrue(s.render_part(part,shader())['still_blocking'])

    def test_native_terrain_retains_layers_uvs_channels_and_material_names(self):
        c=dict(blending='morph',environment_map='none',material_0='diffuse_only',material_1='diffuse_plus_specular',
               material_2='off',material_3='diffuse_only_(four_material_shaders_disable_detail_bump)')
        p=[texture('blend_map')]+[texture(n+f'_m_{i}') for i in (0,1,3) for n in ('base_map','detail_map','bump_map')]
        result=s.terrain_plan(shader(c,p,'rmtr'))
        self.assertFalse(result['still_blocking'])
        t=result['target_authoring_plan'];self.assertEqual(t['target_tag_group'],'shader_terrain')
        self.assertEqual(t['active_layers'],[0,1,3]);self.assertEqual([l['blend_channel'] for l in t['layers']],['R','G','A'])
        self.assertEqual(t['parameters']['base_map_m_1']['transform'],[2,3,.25,.5])
        self.assertEqual(t['layers'][2]['global_material'],'sand')
        c['blending']='dynamic_morph'
        self.assertTrue(s.terrain_plan(shader(c,p,'rmtr'))['still_blocking'])
        p += [dict(name=n,type='real',value=1.) for n in ('dynamic_material','transition_threshold','transition_sharpness')]
        self.assertFalse(s.terrain_plan(shader(c,p,'rmtr'))['still_blocking'])

    def test_native_foliage_keeps_alpha_separate_from_wind(self):
        v=shader(dict(albedo='default',alpha_test='simple',material_model='default'),[texture('base_map'),texture('alpha_test_map')],'rmfl')
        t=s.foliage_plan(v)['target_authoring_plan']
        self.assertEqual(t['target_tag_group'],'shader_foliage')
        self.assertEqual(t['options']['alpha_test'],'from_texture');self.assertTrue(t['alpha_test']['required'])
        self.assertEqual(t['alpha_test']['threshold'],0.5)
        self.assertEqual(t['options']['material_model'],'flat')
        self.assertEqual(t['parameter_bindings']['animation_amplitude_horizontal']['value'],0.0)
        self.assertNotIn('back_light',t['parameter_bindings'])
        v['parameters'].pop()
        self.assertTrue(s.foliage_plan(v)['still_blocking'])

    def test_required_cube_forms_preserve_six_faces_and_mips(self):
        for fmt in ('dxt1','dxt5'):
            b=dict(type='cube map',format=fmt,image_count=1,index=0,depth=1,width=64,height=64,mips=7,
                dds='textures/cube.dds',cube_source=dict(decoded_faces=6,layout='directx_cross_4x3',tiff='textures/cube.tif'))
            result=s.cube_plan(b,[dict(parameter='environment_map')])
            self.assertFalse(result['still_blocking']);self.assertEqual(result['target_authoring_plan']['dimensions'],[64,64,6])
            self.assertFalse(result['target_authoring_plan']['substitute_2d'])
            for key,value in [('image_count',2),('depth',6),('format','dxn'),('type','3D texture')]:
                bad=dict(b,**{key:value});self.assertTrue(s.cube_plan(bad,[])['still_blocking'])


class StructuralRules(unittest.TestCase):
    def test_proven_box_materialless_structure_boundary_still_maps_to_sky(self):
        with tempfile.TemporaryDirectory() as directory:
            bsp=inputs(roots(directory))[1]
            bsp['environment_semantics']['collision_surfaces'][0]['material']=-1
            mapped=model.map_collision(bsp)
            self.assertTrue(any(m.get('special')=='sky' for m in mapped['materials']))
            self.assertFalse(s.untextured_collision(collision())['target_authoring_plan']['sky'])

    def test_materialless_collision_is_not_globally_sky(self):
        result=s.untextured_collision(collision())
        self.assertFalse(result['still_blocking']);t=result['target_authoring_plan']
        self.assertFalse(t['sky']);self.assertEqual(t['face_mode'],'collision_only')
        self.assertIsNone(t['shader_identity'])
        for e in (collision(flags=2),collision(material=0)):
            self.assertTrue(s.untextured_collision(e)['still_blocking'])
        e=collision();e['render_correspondence'][0]['structure_surface_to_triangle_mapping_count']=1
        self.assertTrue(s.untextured_collision(e)['still_blocking'])
        e=collision();e['rings'][0]['source_ring']=None
        self.assertTrue(s.untextured_collision(e)['still_blocking'])

    def test_collision_flags_map_or_explain_the_exact_missing_fact(self):
        for flags in (1,3,5):
            with self.subTest(flags=flags):
                r=s.collision_flags(collision(material=4,flags=flags));self.assertFalse(r['still_blocking'])
                self.assertEqual(r['target_authoring_plan']['ladder'],bool(flags&4))
                self.assertEqual(r['target_authoring_plan']['ray_collision']=='Disabled for invisible/sphere-only faces',bool(flags&2))
        for flags in (9,16,32,64,128):
            self.assertTrue(s.collision_flags(collision(material=4,flags=flags))['still_blocking'])

    def test_unmatched_seam_remains_blocking_without_adding_or_sealing_bsp(self):
        r=authoring.issue('synthetic/world.structure_seams','seams[].selected BSP owners',[1],'missing partner')
        result=s.resolve_record(r,{},[],{})
        self.assertTrue(result['still_blocking']);self.assertEqual(result['semantic_rule_id'],'seam.inactive_neighbor')

    def test_emissive_frustum_is_not_mapped_to_an_unrelated_angle(self):
        r=authoring.issue('synthetic/bsp.scenario_structure_lighting_info','material info',[97],'frustum',source_value={'emissive power':.8,'frustum blend':.5})
        result=s.resolve_record(r,{},[],{})
        self.assertTrue(result['still_blocking']);self.assertNotIn('emissive_focus',result['target_authoring_plan'])

    def test_lighting_material_recovers_properties_without_indexing_minus_one(self):
        m={'imported material index':-1,'properties':[
            {'type':{'name':'lightmap transparency override'},'int-value':1},
            {'type':{'name':'lightmap additive transparency'},'long-value':0x777777}]}
        b={'materials':[{'source_shader':'synthetic/grate.shader'}],'environment_semantics':{'authoring':{'materials':[m]}}}
        r=s.lighting_material(b,0);self.assertFalse(r['still_blocking'])
        t=r['target_authoring_plan'];self.assertIsNone(t['imported_lighting_index'])
        self.assertEqual(t['source_shader'],'synthetic/grate.shader')
        self.assertEqual(t['target_material_properties']['lightmap_additive_transparency'],[119/255]*3)
        m['imported material index']=999;self.assertTrue(s.lighting_material(b,0)['still_blocking'])

    def test_dynamic_lights_keep_palette_identity_and_do_not_invent_membership(self):
        def field(name,value):return dict(element='field',attributes=dict(name=name,value=value))
        row=dict(source_index=0,fields=[field('type',',0'),field('type','frustum'),field('position','1,2,3'),
            field('lightmap light scale','0'),field('lightmap type','use light tag setting'),field('lightmap flags','0')])
        p=dict(scenario_lights=dict(placements=[row],palette=[dict(source_tag='synthetic/light.light')]),
               lighting_by_bsp=[dict(source_bsp_index=0,instances=[{}]*2),dict(source_bsp_index=1,instances=[{}])])
        r=s.scenario_lights(p);self.assertEqual(r['resolution_class'],'RUNTIME_LATER')
        t=r['target_authoring_plan'];self.assertEqual(t['preserved_static_instances'],3)
        self.assertEqual(t['placements'][0]['source_light'],'synthetic/light.light')
        self.assertEqual(t['placements'][0]['target_static_instances'],0)
        row['fields'][3]['attributes']['value']='1'
        self.assertTrue(s.scenario_lights(p)['still_blocking'])


class OriginalAccounting(unittest.TestCase):
    def test_preserved_real_checkpoint_identity_fixture_is_complete(self):
        p=Path(__file__).parent/'fixtures/h3_environment_semantics/voi_original_contract_ids.json'
        fixture=json.loads(p.read_text())
        self.assertEqual(fixture['count'],262);self.assertEqual(len(set(fixture['ids'])),262)
        self.assertFalse(fixture['source_assets_included'])
        self.assertTrue(all(i.startswith('h3-contract-') and len(i)==76 for i in fixture['ids']))

    def test_exact_262_records_survive_reordering_and_resolution(self):
        records=[diagnostic(i) for i in range(262)]
        resolutions=[s.decision('material.constant','NATIVE_DIRECT',dict(value=i)) for i in range(259)]
        resolutions += [s.unknown('source.unknown','synthetic structural gate') for _ in range(3)]
        first=s.report(records,resolutions,records)
        second=s.report(list(reversed(records)),list(reversed(resolutions)),records)
        self.assertEqual(first,second)
        self.assertEqual(first['original_records'],262);self.assertEqual(first['blocking_records'],3)
        self.assertEqual(sum(first['accounting'].values()),262)
        self.assertEqual(len({r['original_record_id'] for r in first['records']}),262)

    def test_missing_original_and_new_source_contract_both_remain_visible(self):
        originals=[diagnostic(i) for i in range(262)]
        current=originals[1:]+[diagnostic(999,'unknown design flags')]
        result=s.report(current,[s.unknown('source.unknown','unknown') for _ in current],originals)
        self.assertEqual(result['original_records'],262);self.assertEqual(result['new_records'],1)
        self.assertEqual(result['blocking_records'],263);self.assertEqual(len(result['records']),263)
        self.assertEqual(sum(result['accounting'].values()),262)

    def test_original_id_ignores_diagnostic_wording_but_not_source_identity(self):
        a=diagnostic(1);b=dict(a,reason='Different wording',status='RESOLVED')
        self.assertEqual(s.record_id(a),s.record_id(b))
        self.assertNotEqual(s.record_id(a),s.record_id(diagnostic(2)))
        with self.assertRaises(ValueError):s.report([a,a],[s.unknown('source.unknown','x')]*2)

    def test_catalog_is_bounded_and_all_rules_have_evidence(self):
        self.assertLessEqual(len(s.RULES),20)
        for rule in s.RULES.values():
            self.assertTrue(rule['meaning']);self.assertTrue(rule['evidence'])
            self.assertTrue(set(rule['evidence']) <= set(s.CATALOG['evidence']))


if __name__=='__main__':unittest.main()

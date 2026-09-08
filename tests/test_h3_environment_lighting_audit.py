"""Synthetic read-only audit/diagnostic invariants; no proprietary assets."""
import base64
from copy import deepcopy
import math
from pathlib import Path
import struct
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment import lighting_audit as a
from port_environment.runtime_bake import intensity_view


def fixture():
    s = dict(type='spot', shape='rectangle', flags='2', color='1,0.5,0.25', intensity='3',
        aspect='0.5', **{'near attenuation bounds':'0,1', 'far attenuation bounds':'2,4',
                        'hotspot size':str(math.pi/4), 'hotspot falloff size':str(math.pi/2)})
    i = {'definition index':'0', 'origin':'2,3,4', 'forward':'1,0,0', 'up':'0,0,1'}
    authored = dict(definitions=[dict(source_fields=s, type=1, shape=1, flags=2, color=[1,.5,.25],
        intensity=3, aspect=.5, near_attenuation=[0,1], far_attenuation=[2,4], hotspot_size=45.,
        hotspot_cutoff=90., hotspot_falloff=1.)], instances=[dict(definition_index=0, origin=[2,3,4], forward=[1,0,0], up=[0,0,1])])
    n = dict(s, flags='use far attenuation, light version 1', **{'hotspot size':'45', 'hotspot cutoff size':'90', 'hotspot falloff speed':'1'})
    ni = dict(i, **{'bounce light control':'1', 'light volume distance':'0', 'light volume intensity scalar':'0',
        'fade out distance':'0', 'fade start distance':'0', 'shader reference index':'-1',
        'bungie light type':'default ligthmap light', 'screen space specular':'version 1 instances',
        'user control':'', 'shader reference':'', 'gel reference':'', 'lens flare reference':''})
    return dict(light_definitions=[s], light_instances=[i]), authored, dict(light_definitions=[n], light_instances=[ni])


class StaticAudit(unittest.TestCase):
    def test_native_shape_angles_and_version_markers_preserve_authored_meaning(self):
        self.assertEqual(a.audit_static(*fixture())['status'], 'STRUCTURAL_MATCH')

    def test_dropped_and_changed_instance_are_reported(self):
        s, p, n = fixture(); n['light_instances'] = []
        self.assertEqual(a.audit_static(s,p,n)['status'], 'MISMATCH')
        s,p,n=fixture();n['light_instances'][0]['origin']='200,300,400'
        self.assertFalse(a.audit_static(s,p,n)['instances'][0]['checks']['origin'])

    def test_every_light_field_detects_drift(self):
        mutations = [('light_definitions','intensity','0'), ('light_definitions','color','0,0,0'),
            ('light_definitions','type','omni'), ('light_definitions','shape','circle'),
            ('light_definitions','hotspot size',str(math.pi/4)), ('light_definitions','hotspot cutoff size','120'),
            ('light_definitions','hotspot falloff speed','0'), ('light_definitions','flags','light version 1'),
            ('light_definitions','far attenuation bounds','0,0'), ('light_instances','bounce light control','0'),
            ('light_instances','forward','0,1,0'), ('light_instances','up','0,0,-1'),
            ('light_instances','bungie light type','analytical'), ('light_instances','fade out distance','2'),
            ('light_instances','gel reference','some/gel')]
        for block, field, value in mutations:
            with self.subTest(field=field):
                s,p,n=fixture();n[block][0][field]=value
                self.assertEqual(a.audit_static(s,p,n)['status'],'MISMATCH')

    def test_authored_drift_is_not_hidden_by_matching_native(self):
        s,p,n=fixture();p['definitions'][0]['intensity']=30;n['light_definitions'][0]['intensity']='30'
        self.assertEqual(a.audit_static(s,p,n)['status'],'MISMATCH')

    def test_nan_does_not_compare_equal(self):
        self.assertFalse(a.equivalent(float('nan'),float('nan')))

    def test_unknown_source_flag_is_not_filtered_out(self):
        s,p,n=fixture();s['light_definitions'][0]['flags']='6';p['definitions'][0]['flags']=6
        self.assertEqual(a.audit_static(s,p,n)['status'],'MISMATCH')


class SourceEvidence(unittest.TestCase):
    def test_split_resource_is_compared_without_double_counting(self):
        scenario=ET.fromstring('<tag><block name="light volumes" value="x,1"><element index="0"><field name="position" value="1,2,3"/></element></block><block name="light volumes palette" value="x,0"/></tag>')
        resource=ET.fromstring('<tag><block name="lights" value="x,1"><element index="0"><field name="position" value="1,2,3"/></element></block><block name="light palette" value="x,0"/></tag>')
        self.assertEqual(a.compare_split_lights(scenario,resource)['status'],'IDENTICAL_SPLIT_COPY')
        resource.find('.//field').set('value','4,5,6')
        self.assertEqual(a.compare_split_lights(scenario,resource)['status'],'NEEDS_RECONCILIATION')

    def test_duplicate_type_labels_do_not_replace_palette_with_volume_enum(self):
        root=ET.fromstring('''<tag><block name="light volumes" value="test,1"><element index="0">
            <field name="type" type="short block index" value="blue,3"/>
            <field name="type" type="char enum" value="biped"/>
            <field name="type" type="short enum" value="sphere"/>
            <field name="position" value="1,2,3"/><field name="rotation" value="0,0,0"/>
            <field name="lightmap light scale" value="0"/></element></block></tag>''')
        r=a.scenario_placements(root)[0]
        self.assertEqual(r['palette_index'],3);self.assertEqual(r['volume_shape'],'sphere')
        self.assertIn('not established',r['lightmap_scale_interpretation'])
        self.assertEqual(len(r['ordered_source_fields']),6)

    def test_constant_functions_are_source_states_not_arbitrary_time(self):
        b=bytearray(32);b[:3]=bytes([1,0x24,0]);struct.pack_into('<f',b,4,2.)
        encoded=base64.b64encode(b).decode().rstrip('=')
        self.assertEqual(a.constant_function(encoded)['value'],2.)
        b[2]=2;struct.pack_into('<I',b,4,0x123456)
        self.assertEqual(a.constant_function(base64.b64encode(b).decode())['value'],[0x12/255,0x34/255,0x56/255])
        b[1]|=1
        with self.assertRaises(ValueError):a.constant_function(base64.b64encode(b).decode())

    def test_packed_tree_uses_plane_signed_distance_and_leaf_identity(self):
        tree={'nodes_u64':[0 | (0x800000<<16) | (0x800001<<40)], 'planes':[[1,0,0,2]], 'leaf_clusters':[6,11]}
        self.assertEqual(a.locate_point(tree,[1,0,0])['clusters'],[6])
        self.assertEqual(a.locate_point(tree,[3,0,0])['clusters'],[11])
        self.assertEqual(a.locate_point(tree,[2,0,0])['clusters'],[6,11])

    def test_solid_cycle_and_corruption_cannot_fabricate_membership(self):
        tree={'nodes_u64':[(0xffffff<<16)|(0x800000<<40)],'planes':[[1,0,0,0]],'leaf_clusters':[6]}
        self.assertEqual(a.locate_point(tree,[-1,0,0])['status'],'BOUNDARY_OR_OUTSIDE')
        self.assertTrue(a.locate_point(tree,[0,0,0])['solid_branch'])
        tree['nodes_u64']=[0]
        with self.assertRaisesRegex(ValueError,'Cyclic'):a.locate_point(tree,[1,0,0])
        tree['nodes_u64']=[(0x800010<<40)]
        with self.assertRaisesRegex(ValueError,'leaf'):a.locate_point(tree,[1,0,0])

    def test_triangle_distance_uses_surface_not_centroid(self):
        self.assertEqual(a.closest_triangle([1,1,2],[0,0,0],[100,0,0],[0,100,0]),(1,1,0))
        self.assertEqual(a.closest_triangle([-1,0,0],[0,0,0],[100,0,0],[0,100,0]),[0,0,0])
        self.assertEqual(a.closest_triangle([.5,1,0],[0,0,0],[1,0,0],[2,0,0]),(.5,0,0))


class ControlledDiagnostic(unittest.TestCase):
    def test_diagnostic_readback_rejects_other_light_and_material_changes(self):
        _,_,native=fixture();native['materials']=[{'emissive power':'3.2'}]
        actual=deepcopy(native);actual['light_definitions'][0]['intensity']='30'
        a.assert_intensity_delta(native,actual,10)
        actual['light_instances'][0]['bounce light control']='0'
        with self.assertRaisesRegex(ValueError,'bounce'):a.assert_intensity_delta(native,actual,10)
        actual['light_instances']=deepcopy(native['light_instances']);actual['materials'][0]['emissive power']='32'
        with self.assertRaisesRegex(ValueError,'emissive'):a.assert_intensity_delta(native,actual,10)

    def test_only_selected_definition_power_changes(self):
        _, light, _=fixture()
        plan=dict(bsps=[{'source_index':0},{'source_index':1}], lighting_by_bsp=[deepcopy(light),deepcopy(light)], source={'sha':'preserved'})
        saved=deepcopy(plan);view,index=intensity_view(plan,1,10)
        self.assertEqual(index,1);self.assertEqual(plan,saved)
        self.assertEqual(view['lighting_by_bsp'][0],saved['lighting_by_bsp'][0])
        self.assertEqual(view['lighting_by_bsp'][1]['definitions'][0]['intensity'],30)
        view['lighting_by_bsp'][1]['definitions'][0]['intensity']=3
        self.assertEqual(view,plan)

    def test_unknown_bsp_and_invalid_power_scale_fail_before_writes(self):
        _, light, _=fixture();p=dict(bsps=[{'source_index':1}],lighting_by_bsp=[light])
        for value in (0,1,-1,101,float('nan'),float('inf')):
            with self.assertRaises(ValueError):intensity_view(p,1,value)
        with self.assertRaises(ValueError):intensity_view(p,2,10)
        light['definitions'][0]['intensity']=0
        with self.assertRaises(ValueError):intensity_view(p,1,10)


if __name__=='__main__':unittest.main()

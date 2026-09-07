"""Pure compiler invariants. Synthetic geometry; no fabricated Tool successes."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment import DEFAULT_NAMESPACE, SOURCE_SCENARIO
from port_environment import fixtures, model
from port_environment.paths import OutputPaths, Ownership, atomic_json, digest, relative
from port_environment.validation import geometry_errors, lighting_evidence, NATIVE_TAG_EXTENSIONS

FIXTURES = Path(__file__).parent/'fixtures/h3_reach_box'


def roots(directory):
    h3, reach = Path(directory)/'H3EK', Path(directory)/'HREK'
    for kit in (h3, reach):
        for kind in ('tags', 'data'):
            (kit/kind).mkdir(parents=True)
    return OutputPaths(h3, reach)


def inputs(paths):
    shader = 'levels/test/box/shaders/concrete_floor.shader'
    sky_shader = 'levels/test/box/sky/shaders/sky_dome.shader'
    def vertex(p):
        return dict(position=p, normal=[0,0,1], uvs=[[0,0,0]], weights=[], color=[1,1,1])
    vertices = [vertex([-100,-100,0]), vertex([100,-100,0]), vertex([0,100,0])]
    def instance(index, obj, name, parent=-1):
        return dict(id=index, object=obj, name=name, parent=parent, inheritance_flag=0,
                    position=[0,0,0], rotation=[1,0,0,0], scale=1,
                    pivot_position=[0,0,0], pivot_rotation=[1,0,0,0], pivot_scale=1, bone_groups=[])
    source_bsp = 'levels/test/box/box.scenario_structure_bsp'
    scene = dict(source_tag=SOURCE_SCENARIO, game='halo3_mcc', bsp_entries=[dict(status='extracted')])
    bsp = dict(format='foundry.h3-bsp', version=1, units='ass_100_per_world_unit', source_tag=source_bsp,
               materials=[dict(source_shader=shader), dict(source_shader=None)],
               objects=[dict(id=0, kind='mesh', vertices=deepcopy(vertices), triangles=[dict(material=0,vertices=[0,1,2])]),
                        dict(id=1, kind='mesh', vertices=deepcopy(vertices), triangles=[dict(material=1,vertices=[0,1,2])])],
               instances=[instance(0,-1,'root'), instance(1,0,'cluster_0',0), instance(2,1,'@CollideOnly',0)])
    bsp['environment_semantics'] = dict(version=1, collision_object=1, cluster_sky_indices=[0],
        collision_materials=[shader], collision_surfaces=[dict(source_surface=0, material=0, flags=0,
                                                              triangle_start=0, triangle_count=1)])
    sky = dict(format='foundry.h3-object', version=1, game='halo3_mcc', units='jms_x100',
               source_tag='levels/test/box/sky/sky.scenery',
               dependencies=dict(model='levels/test/box/sky/sky.model',render_model='levels/test/box/sky/sky.render_model'),
               shader_paths=[sky_shader], render=dict(vertices=vertices, triangles=[dict(material=0,vertices=[0,1,2])],
                   materials=[dict(name='sky_dome')], nodes=[dict(parent=-1,position=[0,0,0],rotation=[-1,0,0,0])]))
    shaders = dict(shaders={p:dict(status='resolved_snapshot',group='rmsh',categories=[],parameters=[])
                           for p in (shader,sky_shader)}, bitmaps={})
    scenario = fixtures.parse((FIXTURES/'h3.scenario.xml').read_bytes())
    lighting = fixtures.parse((FIXTURES/'h3.lighting.xml').read_bytes())
    sky_xml = fixtures.parse(b'<tag group="scenery" id="levels\\test\\box\\sky\\sky"/>')
    sky_render_xml = fixtures.parse((FIXTURES/'h3.sky_lighting.xml').read_bytes())
    for source in (SOURCE_SCENARIO,source_bsp,'levels/test/box/box.scenario_structure_lighting_info',
                   sky['source_tag'],*sky['dependencies'].values(),shader,sky_shader,'shaders/shader.render_method_definition'):
        path = paths.h3_tags/source
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('synthetic tag identity '+source)
    return scene,bsp,sky,shaders,scenario,lighting,sky_xml,sky_render_xml


class PairedXML(unittest.TestCase):
    def test_tool_zero_exit_does_not_hide_geometry_errors(self):
        log='Writing errors to tag\n[Foundry Icons] Failed to load icon\n(structure_bsp proof_box_bsp) open edge: h3_bsp_0: open edge (#1)\n'
        self.assertEqual(len(geometry_errors(log)),1)
        self.assertIn('.scenario_structure_bsp',NATIVE_TAG_EXTENSIONS)
        self.assertNotIn('.probestore',NATIVE_TAG_EXTENSIONS)

    def test_lighting_logs_must_have_energy_and_no_failed_phases(self):
        valid = 'DC:0.00%of5.604029E+04 Linear:1.19%of5.471963E+04 Quad:50.00%of2.587128E+04'
        self.assertFalse(lighting_evidence([valid])['errors'])
        self.assertTrue(lighting_evidence(['DC:0%of0 Linear:0%of0 Quad:0%of0'])['errors'])
        self.assertTrue(lighting_evidence([valid,'LIGHTMAPPER FAILED: job not needed'])['errors'])

    def test_nested_and_flattened_scenario_authoring(self):
        h3 = fixtures.scenario_semantics(fixtures.parse((FIXTURES/'h3.scenario.xml').read_bytes()))
        reach = fixtures.scenario_semantics(fixtures.parse((FIXTURES/'reach.scenario.xml').read_bytes()))
        self.assertEqual(len(h3['bsps']), len(reach['bsps']))
        self.assertEqual(len(h3['skies']), 1)
        self.assertFalse(h3['has_top_level_designs'])
        self.assertTrue(reach['has_top_level_designs'])
        self.assertEqual(h3['player_starts'], [])
        self.assertEqual(reach['player_starts'], [])
        self.assertEqual(len(h3['zone_sets']), 0)
        self.assertEqual(len(reach['zone_sets']), 1)

    def test_only_known_malformed_export_markers_are_normalized(self):
        raw = b'<tag><field name="null" value=",\xff\xff\xff\xff" type="tag reference"/><field name="api resource" value="<unavailable>" type="pageable resource"/></tag>'
        tag = fixtures.parse(raw)
        self.assertEqual(fixtures.field(tag,'null'), ',NULL')
        self.assertEqual(fixtures.field(tag,'api resource'), '<unavailable>')
        with self.assertRaises(Exception):
            fixtures.parse(b'<tag><field name="unknown" value="\xff"/></tag>')
        with self.assertRaises(ValueError):
            fixtures.parse(b'<!DOCTYPE tag [<!ENTITY a "bad">]><tag/>')

    def test_no_resource_or_instruction_interpretation(self):
        tag = fixtures.parse(b'<tag><field name="instructions" value="copy stock box"/><field name="data" value="execute" type="data"/></tag>')
        self.assertEqual(fixtures.field(tag,'instructions'), 'copy stock box')
        self.assertNotIn('data', fixtures.fields(tag))

    def test_count_and_duplicate_field_rejected(self):
        with self.assertRaises(ValueError):
            fixtures.block(fixtures.parse(b'<tag><field name="x" type="block" value="2"/><element index="0"/></tag>'), 'x')
        with self.assertRaises(ValueError):
            fixtures.field(fixtures.parse(b'<tag><field name="x"/><field name="x"/></tag>'),'x')

    def test_catalog_has_evidence_and_allowed_transformations(self):
        catalog = json.loads(Path(model.__file__).with_name('mappings.json').read_text())
        ids = set()
        for row in catalog['rules']:
            self.assertNotIn(row['id'],ids)
            ids.add(row['id'])
            for key in ('source_group','source_path','target_group','target_path','evidence','confidence'):
                self.assertTrue(row[key])
            self.assertIn(row['transform'], {'direct','moved','split','merged','default','regenerate','omit'})
        self.assertIn('scenario.design',ids)
        self.assertIn('scenario.runtime',ids)


class EnvironmentModel(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = roots(self.temp.name)
        self.args = inputs(self.paths)

    def plan(self):
        return model.construct(self.paths,*self.args)

    def test_deterministic_plan_and_geometry_authenticity(self):
        plan = self.plan()
        self.assertEqual(plan, self.plan())
        self.assertEqual(plan['bsp']['source_render']['triangles'], 1)
        self.assertEqual(plan['bsp']['source_collision']['triangles'], 1)
        self.assertEqual(plan['bsp']['source_render']['bounds_world'], ([-1,-1,0],[1,1,0]))
        self.assertEqual(plan['scenario']['spawn']['position_world'], [0,0,0.2])
        self.assertEqual(plan['scenario']['spawn']['classification'],'TARGET_DEFAULT')
        self.assertEqual(plan['scenario']['structure_designs'], [])
        self.assertEqual(plan['source']['hashes'][SOURCE_SCENARIO],digest(self.paths.source(SOURCE_SCENARIO)))
        self.assertNotIn('zone set pvs',plan['scenario'])
        self.assertTrue(plan['sky']['destination'].startswith(DEFAULT_NAMESPACE+'/'))

    def test_live_source_hash_change_changes_plan(self):
        before = self.plan()['plan_sha256']
        self.paths.source(SOURCE_SCENARIO).write_text('changed source')
        self.assertNotEqual(before,self.plan()['plan_sha256'])

    def test_collision_sky_mapping_preserves_surface_coverage(self):
        bsp = deepcopy(self.args[1])
        bsp['environment_semantics']['collision_surfaces'][0]['material'] = -1
        mapped = model.map_collision(bsp)
        t = mapped['objects'][1]['triangles'][0]
        self.assertEqual(t['surface_type'], 'sky')
        self.assertEqual(mapped['materials'][t['material']]['name'], '+sky0')
        self.assertEqual(t['vertices'], [0,1,2])
        for key, value in [('flags',1),('triangle_count',2),('triangle_start',1),('material',-2)]:
            bad = deepcopy(bsp)
            bad['environment_semantics']['collision_surfaces'][0][key]=value
            with self.subTest(key=key), self.assertRaises(ValueError):model.map_collision(bad)

    def test_source_sky_lighting_is_not_replaced_with_a_proof_sun(self):
        light = self.plan()['lighting']['sky']
        self.assertEqual(len(light['source_samples']),2)
        self.assertAlmostEqual(light['sun_irradiance'][0],47793*5.65487e-05)
        self.assertGreater(light['sun_size_degrees'],0)
        self.assertEqual(light['classification'],'GENERATED')

    def test_world_and_pivot_transforms_are_composed_once(self):
        bsp = self.args[1]
        bsp['instances'][0]['position'] = [100,0,0]
        bsp['instances'][1]['pivot_position'] = [0,200,0]
        plan = self.plan()
        self.assertEqual(plan['bsp']['source_render']['bounds_world'], ([0,1,0],[2,3,0]))
        self.assertEqual(plan['bsp']['meshes'][0]['triangles'][0]['vertices'], [0,1,2])

    def test_unproven_geometry_contracts_fail(self):
        for change in ('cycle','skin','xref','negative','portal','nan','material'):
            args = deepcopy(self.args)
            bsp = args[1]
            if change=='cycle':bsp['instances'][0]['parent']=1
            if change=='skin':bsp['objects'][0]['vertices'][0]['weights']=[[0,1]]
            if change=='xref':bsp['objects'][0]['xref_path']='stock.scenery'
            if change=='negative':bsp['instances'][1]['scale']=-1
            if change=='portal':bsp['instances'][1]['name']='+portal'
            if change=='nan':bsp['objects'][0]['vertices'][0]['position'][0]=float('nan')
            if change=='material':bsp['objects'][0]['triangles'][0]['material']=-1
            with self.subTest(change=change), self.assertRaises(ValueError):
                model.construct(self.paths,*args)

    def test_different_mission_or_relationship_rejected(self):
        args = deepcopy(self.args)
        args[0]['source_tag']='levels/solo/040_voi/040_voi.scenario'
        with self.assertRaises(ValueError):model.construct(self.paths,*args)
        args = deepcopy(self.args)
        args[2]['source_tag']='levels/test/box/box_sky.scenery'
        with self.assertRaises(ValueError):model.construct(self.paths,*args)

    def test_nonzero_source_lighting_not_silently_dropped(self):
        args = list(self.args)
        args[5] = fixtures.parse((FIXTURES/'h3.lighting.xml').read_bytes().replace(b'value="0" type="real"',b'value="4" type="real"'))
        with self.assertRaises(ValueError):model.construct(self.paths,*args)

    def test_bitmap_resource_requires_single_2d_pixels(self):
        bitmap = dict(image_count=1,type='2D texture',depth=1,index=0,width=4,height=4,format='dxn',preview='textures/00000.tif')
        self.assertIn('TIFF',model.bitmap_strategy(bitmap)['strategy'])
        for key,value in [('type','cubemap'),('depth',3),('image_count',2),('index',1),('width',0)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                model.bitmap_strategy(dict(bitmap,**{key:value}))


class OutputSafety(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths=roots(self.temp.name)

    def test_reject_stock_traversal_devices_and_foreign_roots(self):
        for name in ('../outside','levels/test/box','levels/h3_port/proof/extra','levels/h3_port/../box',
                     'levels/h3_port/CON','levels/h3_port/proof.','levels/h3_port/proof:ads','C:/outside'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                OutputPaths(self.paths.h3,self.paths.reach,name)
        for name in ('../file','C:\\file','file:stream','CON.txt','//server/share','a//b'):
            with self.assertRaises(ValueError):relative(name)
        with self.assertRaises(ValueError):OutputPaths(self.paths.h3,self.paths.h3)
        with self.assertRaises(ValueError):Ownership(self.paths,self.paths.reach/'reports/proof')

    def test_exact_hash_ownership_is_required_even_after_failure(self):
        owner=Ownership(self.paths,Path(self.temp.name)/'build')
        owner.directory.mkdir()
        self.assertEqual(owner.preflight(),{})
        path=self.paths.destination('tags','proof_box.scenario')
        path.parent.mkdir(parents=True)
        path.write_text('tool partial output')
        with self.assertRaises(ValueError):owner.preflight()
        owner.save('FAILED',self.paths.snapshot(),'test-build')
        self.assertEqual(len(owner.preflight()),1)
        path.write_text('user edited this')
        with self.assertRaises(ValueError):owner.preflight()

    def test_interrupted_build_is_not_adopted(self):
        owner=Ownership(self.paths,Path(self.temp.name)/'build')
        owner.directory.mkdir()
        owner.save('BUILDING',{},'test-build')
        with self.assertRaisesRegex(ValueError,'interrupted'):owner.preflight()

    def test_redirected_output_is_rejected(self):
        namespace=self.paths.destination('tags')
        namespace.parent.mkdir(parents=True)
        outside=Path(self.temp.name)/'outside'
        outside.mkdir()
        try:os.symlink(outside,namespace,target_is_directory=True)
        except OSError:self.skipTest('Symlink creation unavailable for this test account')
        with self.assertRaises(ValueError):self.paths.destination('tags','proof_box.scenario')


if __name__=='__main__':
    unittest.main()

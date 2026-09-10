"""Pure native lowering tests; no proprietary geometry or kit required."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment import native_contracts, snapshot, breakable_geometry, native_validation, native_topology
from port_environment.paths import OutputPaths, Ownership
from port_environment import native_cache
from port_environment.native_world import match_triangles
from port_environment.validation import native_xml_references
from port_environment import resume
from test_h3_environment_remaining_rules import glass_fixture


class NativeContracts(unittest.TestCase):
    def test_validation_resume_rejects_changed_added_or_missing_outputs(self):
        expected={'tags/generated.shader':'sha'}
        resume.require_outputs(dict(expected),expected)
        for actual in ({},{'tags/generated.shader':'changed'},{**expected,'extra':'sha'}):
            with self.assertRaises(ValueError):resume.require_outputs(actual,expected)
        with self.assertRaises(ValueError):resume.require_outputs({},{})

    def test_validation_resume_requires_geometry_faux_and_read_only_pending_jobs(self):
        worker=dict(stage='native tag validation',lighting_status='REACH_FAUX_DIRECT_ONLY',geometry_tool_errors=[],
            lighting_evidence=dict(errors=[],vmf_energy_statistics=[1,2]),
            tool_invocations=[dict(command=['tool','import'],exit_code=0),dict(command=['tool','export-tag-to-xml'])])
        resume.require_completed_authoring(worker)
        for key,value in [('stage','lighting'),('lighting_status','NOT_RUN'),('geometry_tool_errors',['open edge']),
                          ('lighting_evidence',dict(errors=['failed'],vmf_energy_statistics=[1])),
                          ('lighting_evidence',dict(errors=[],vmf_energy_statistics=[float('nan')]))]:
            with self.assertRaises(ValueError):resume.require_completed_authoring(dict(worker,**{key:value}))
        worker['tool_invocations'][-1]['command'][1]='import'
        with self.assertRaises(ValueError):resume.require_completed_authoring(worker)

    def test_validation_resume_xml_requires_successful_tool_and_matching_hashes(self):
        from port_environment.paths import digest
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for kit in ('source','target'):
                for folder in ('data','tags'):(root/kit/folder).mkdir(parents=True)
            paths=OutputPaths(root/'source',root/'target','levels/h3_port/synthetic/slice',allow_nested=True)
            source=paths.destination('tags','glass.shader');source.parent.mkdir(parents=True);source.write_bytes(b'native')
            prior=root/'run';(prior/'native-tag-xml').mkdir(parents=True)
            xml=prior/'native-tag-xml/glass.xml';xml.write_text('<tag/>')
            row=dict(path=str(xml),sha256=digest(xml),status='WELL_FORMED_STREAMED')
            command=dict(command=['tool','export-tag-to-xml',str(source),str(xml)],exit_code=0)
            worker=dict(tool_invocations=[command],native_xml_validation=[row])
            outputs={source.relative_to(paths.reach).as_posix():digest(source)}
            cache=resume.xml_cache(prior,worker,paths,outputs)
            self.assertEqual(cache[str(source)]['source_sha256'],digest(source))
            previous_report=prior/'worker-report.json';previous_report.write_text(json.dumps(worker))
            replay=root/'replay';replay.mkdir()
            (replay/'worker-config.json').write_text(json.dumps(dict(validation_only=True,
                previous_worker_report=str(previous_report),previous_worker_sha256=digest(previous_report))))
            self.assertEqual(resume.xml_cache(replay,worker,paths,outputs),cache)
            previous_report.write_text('{}')
            with self.assertRaisesRegex(ValueError,'history changed'):resume.xml_cache(replay,worker,paths,outputs)
            command['exit_code']=1
            with self.assertRaises(ValueError):resume.xml_cache(prior,worker,paths,outputs)
            command['exit_code']=0;xml.write_text('<tag changed="true"/>')
            with self.assertRaises(ValueError):resume.xml_cache(prior,worker,paths,outputs)

    def test_validation_journal_rejects_import_and_faux(self):
        from port_environment.worker import ToolJournal
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            journal=object.__new__(ToolJournal)
            journal.paths=type('Paths',(),{'reach':root.resolve()})()
            journal.report={'validation_only':True}
            for action in ('import','faux_data_sync','generate-specified-template'):
                with self.assertRaisesRegex(ValueError,'Validation-only'):
                    journal.check([root/'tool.exe',action,'unused'])

    def test_native_xml_streaming_preserves_exact_sentinels_and_rejects_entities(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'native.xml'
            data=b'<tag>\n<field name="flags" value="shared entry point compilation&shared pixel shader compilation" type="word flags"/>\n<field value="levels\\generated\\bsp" type="tag reference"/>\n<field value="<unavailable>" type="pageable resource"/>\n<field value=",\xff\xff\xff\xff" type="tag reference"/>\n</tag>'
            path.write_bytes(data)
            for chunk in (1,7,64,1024):
                self.assertEqual(native_xml_references(path,chunk),{'levels/generated/bsp'})
            for bad in (b'<!DOCTYPE tag [<!ENTITY x "y">]><tag/>',b'<other/>',b'<tag>',
                        b'<tag><field name="flags" value="one&unknown;" type="word flags"/></tag>',
                        b'<tag><field value="one&two" type="tag reference"/></tag>'):
                path.write_bytes(bad)
                with self.assertRaises(Exception):native_xml_references(path,7)

    def test_native_boundary_matching_allows_roundoff_but_preserves_winding(self):
        triangle=[[.00049,0,0],[1,0,0],[0,1,0]]
        native=[[1,0,0],[0,1,0],[.00051,0,0]]
        self.assertAlmostEqual(match_triangles([triangle],[native]),.00002)
        with self.assertRaisesRegex(ValueError,'winding'):match_triangles([triangle],[native[::-1]])
        with self.assertRaisesRegex(ValueError,'count'):match_triangles([triangle],[])
        native[2][0]=.01
        with self.assertRaisesRegex(ValueError,'geometry'):match_triangles([triangle],[native])
        native[2][0]=float('nan')
        with self.assertRaisesRegex(ValueError,'nonfinite'):match_triangles([triangle],[native])

    def test_bitmap_cache_recovers_prior_success_but_rejects_changed_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for kit in ('source','target'):
                for folder in ('data','tags'):(root/kit/folder).mkdir(parents=True)
            paths=OutputPaths(root/'source',root/'target','levels/h3_port/synthetic/slice',allow_nested=True)
            reports=root/'reports';prior=reports/'runs'/'earlier';prior.mkdir(parents=True)
            name=paths.namespace+'/bitmaps/source'
            files=[]
            for kind,suffix in [('data','.tif'),('tags','.bitmap')]:
                file=paths.destination(kind,'bitmaps/source'+suffix)
                file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(b'validated source pixels')
                files.append(dict(path=kind+'/'+name+suffix,sha256=native_cache.digest(file)))
            plan=dict(plan_sha256='accepted',bitmaps={})
            config=dict(report_directory=str(reports),snapshot_input=dict(verified_files={'source':'hash'}))
            receipt=dict(plan_sha256='accepted',source_validation_basis=config['snapshot_input'],generated_files=files,
                worker=dict(tool_invocations=[dict(command=['tool','reimport-bitmaps-single',name],status='ACCEPTED')],
                    bitmap_builds=[dict(destination=name+'.tif',pixel_export=native_cache.PIXEL_EXPORT)]))
            report_name=paths.asset+'_build_report.json'
            (prior/report_name).write_text(json.dumps(receipt))
            (reports/report_name).write_text(json.dumps(dict(status='FAILED')))
            self.assertEqual(set(native_cache.previous_bitmaps(paths,plan,config,{name})),{name})
            paths.destination('data','bitmaps/source.tif').write_bytes(b'edited')
            self.assertEqual(native_cache.previous_bitmaps(paths,plan,config,{name}),{})

    def test_two_sided_collision_requires_reverse_ring_and_equal_semantics(self):
        record=dict(vertices=[dict(position=p) for p in ([0,0,0],[100,0,0],[100,100,0],[0,100,0])],
            triangles=[dict(vertices=t,material=0) for t in ([0,1,2],[0,2,3],[3,2,1],[3,1,0])])
        surfaces=[dict(source_surface=i,triangle_start=i*2,triangle_count=2,material=0,flags=1) for i in range(2)]
        before=deepcopy(record)
        authored=native_topology.collision_polygons(record,surfaces,'synthetic')
        self.assertEqual(record,before)
        self.assertEqual(len(authored['triangles']),1)
        self.assertEqual(len(authored['triangles'][0]['vertices']),4)
        self.assertEqual(authored['native_topology']['paired_two_sided_surfaces'],[[0,1]])
        surfaces[1]['material']=1
        self.assertEqual(len(native_topology.collision_polygons(record,surfaces,'synthetic')['triangles']),2)
        surfaces[1]['material']=0;surfaces[1]['flags']=3
        self.assertEqual(len(native_topology.collision_polygons(record,surfaces,'synthetic')['triangles']),2)

    def test_render_sliver_filter_never_changes_unified_breakable_collision(self):
        record=dict(face_mode='breakable',vertices=[dict(position=p) for p in ([0,0,0],[1,0,0],[2,0,0])],
            triangles=[dict(vertices=[0,1,2],material=0)])
        self.assertEqual(len(native_topology.render_slivers(deepcopy(record),'glass')['triangles']),1)
        record['face_mode']='render_only'
        lowered=native_topology.render_slivers(record,'render')
        self.assertEqual(lowered['triangles'],[])
        self.assertEqual(lowered['render_slivers']['removed'][0]['source_face'],0)

    def test_owned_shader_infrastructure_does_not_authorize_stock_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for kit in ('source','target'):
                for folder in ('data','tags'):(root/kit/folder).mkdir(parents=True)
            paths=OutputPaths(root/'source',root/'target','levels/h3_port/synthetic/slice',allow_nested=True)
            owned=paths.owned_tag('shaders/h3_port/synthetic/slice/shader.render_method_definition')
            owned.parent.mkdir(parents=True);owned.write_bytes(b'synthetic definition')
            ownership=Ownership(paths,root/'report');ownership.directory.mkdir()
            with self.assertRaisesRegex(ValueError,'unowned'):ownership.preflight()
            ownership.save('COMPLETE',paths.snapshot(),'synthetic')
            self.assertEqual(len(ownership.preflight()),1)
            owned.write_bytes(b'edited')
            with self.assertRaisesRegex(ValueError,'modified'):ownership.preflight()
            for foreign in ('shaders/shader.render_method_definition','levels/stock/bsp.scenario_structure_bsp',
                'shaders/h3_port/other/shader.render_method_definition'):
                with self.assertRaises(ValueError):paths.owned_tag(foreign)
            proof=OutputPaths(root/'source',root/'target')
            with self.assertRaises(ValueError):proof.owned_tag('shaders/h3_port/proof_box/shader.render_method_definition')

    def test_native_lighting_readback_rejects_zero_and_nonfinite_power(self):
        native_validation.close([.8,.2643111,1,2],[.8,.2643111,1,2],'emission')
        for actual in (0,float('nan'),float('inf')):
            with self.assertRaises(ValueError):native_validation.close(actual,.8,'power')
        with self.assertRaises(ValueError):native_validation.close([1,2],[1,2,3],'origin')
        with self.assertRaises(ValueError):native_validation.close(.8,float('nan'),'source power')

    def test_unexposed_parameters_have_bounded_semantics_not_fallbacks(self):
        contract=dict(options=dict(material_model='two_lobe_phong'),approximation=dict(source='glass'))
        for name,value in [('bump_detail_coefficient',1),('order3_area_specular',False),
            ('analytical_anti_shadow_control',.15),('fresnel_coefficient',.01),('fresnel_curve_bias',0)]:
            result=native_contracts.unexposed_parameter(dict(name=name,value=value),contract)
            self.assertTrue(result['evidence'])
        tint=dict(name='specular_tint',type='color',value=[.3,.4,.5,1])
        result=native_contracts.unexposed_parameter(tint,contract)
        self.assertEqual(set(result['target_parameters']),{'normal_specular_tint','glancing_specular_tint'})
        self.assertTrue(all(p['value']==tint['value'] for p in result['target_parameters'].values()))
        for name,value in [('bump_detail_coefficient',.5),('order3_area_specular',True),('opacity',.5),('visibility',0)]:
            with self.assertRaises(ValueError):native_contracts.unexposed_parameter(dict(name=name,value=value),contract)

    def test_brdf_approximation_preserves_alpha_and_texture_identity(self):
        row=dict(source_categories=[dict(category='material_model',option='glass'),
            dict(category='blend_mode',option='alpha_blend')],source_parameters=[dict(name='base_map',type='bitmap',bitmap='source-glass#0')])
        target=native_contracts.material(row)
        self.assertEqual(target['options']['material_model'],'two_lobe_phong')
        self.assertEqual(target['options']['blend_mode'],'alpha_blend')
        self.assertEqual(target['parameters']['base_map']['bitmap'],'source-glass#0')
        self.assertTrue(target['approximation']['fidelity_loss'])

    def test_unified_glass_preserves_uvs_and_requires_full_proof(self):
        source=glass_fixture()
        proof=breakable_geometry.prove(*source,units='ass_100_per_world_unit')
        render=source[0];before=deepcopy(render)
        native=native_contracts.unified_mesh(render,proof)
        self.assertEqual(render,before)
        self.assertEqual(native['face_mode'],'breakable')
        self.assertEqual(len(native['triangles']),2)
        self.assertEqual([v['uvs'] for v in native['vertices']],[v['uvs'] for v in render['vertices']])
        proof['all_collision_rings_covered']=False
        with self.assertRaises(ValueError):native_contracts.unified_mesh(render,proof)

    def test_collision_proxy_never_accepts_breakability_or_unknown_flags(self):
        for flags in (8,9,16,32):
            with self.subTest(flags=flags),self.assertRaises(ValueError):native_contracts.collision_face(flags)
        self.assertEqual(native_contracts.collision_face(3),dict(face_mode='sphere_collision_only',two_sided=True,ladder=False))
        self.assertTrue(native_contracts.collision_face(4)['ladder'])
        self.assertEqual(native_contracts.collision_face(0)['face_mode'],'collision_only')

    def test_explicit_native_groups_preserve_cutout_and_terrain_contracts(self):
        for group in ('shader_terrain','shader_foliage'):
            row=dict(source_categories=[],source_parameters=[],semantic_authoring=[dict(still_blocking=False,
                target_authoring_plan=dict(target_node='foundry_reach.'+group,options=dict(alpha_test='from_texture'),
                    parameter_bindings=dict(alpha_test_map=dict(type='bitmap',bitmap='synthetic#0'))))])
            target=native_contracts.material(row)
            self.assertEqual(target['target_node'],'foundry_reach.'+group)
            self.assertEqual(target['parameters']['alpha_test_map']['name'],'alpha_test_map')
            self.assertEqual(target['options']['alpha_test'],'from_texture')
            self.assertNotIn('name',row['semantic_authoring'][0]['target_authoring_plan']['parameter_bindings']['alpha_test_map'])

    def test_frozen_input_hashes_reject_edits_without_reading_live_tags(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'source.json';path.write_text('{}')
            files={str(path):snapshot.digest(path)}
            snapshot.verify_files(files)
            path.write_text('{"edit":true}')
            with self.assertRaisesRegex(ValueError,'snapshot input changed'):snapshot.verify_files(files)


if __name__=='__main__':unittest.main()

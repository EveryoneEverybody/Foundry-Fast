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
from test_h3_environment_remaining_rules import glass_fixture


class NativeContracts(unittest.TestCase):
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

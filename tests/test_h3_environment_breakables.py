"""Synthetic BSP breakable placement reporting, without tag payloads."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment import authoring, breakables, semantics


def fixture():
    tag = 'synthetic/world.scenario_structure_bsp'
    reference = {'render method':dict(path='synthetic\\glass', extension='shader')}
    surfaces = [dict(source_surface=i,material=material,flags=9 if i < 2 else 0,
        **{'breakable surface set':143,'breakable surface':i},
        ring=dict(source_edges=[],source_vertices=[0,1,2],decoded_vertices=[0,1,2]))
        for i,material in enumerate((0,-1,1))]
    definition = {'source_index':0, 'mesh index':0, 'checksum':123,
        'breakable surface sets':[{'supported bitfield':None,'source_index':0}],
        'collision_mesh':dict(source_surfaces=surfaces,vertices=[dict(position=p) for p in ([0,0,0],[1,0,0],[0,1,0])]),
        'surfaces':[dict(source_index=i,structure_surface_to_triangle_mapping_count=0) for i in range(3)]}
    placements = [dict(source_index=i,name=f'?glass_{i}',position=[i,0,0],**{'instance definition':0}) for i in (10,11)]
    bsp = dict(source_tag=tag,bsp_index=2,
        materials=[dict(source_shader='synthetic/other.shader',name='other'),dict(source_shader='synthetic/glass.shader',name='glass')],
        environment_semantics=dict(authoring=dict(definitions=[definition],instances=placements,
            render_meshes=[dict(parts=[{'render method index':1,'source_index':0}])],
            materials=[{},reference],collision_materials=[reference,{'render method':dict(path='synthetic/other',extension='shader')}])))
    record = authoring.issue(tag,'instanced geometry definitions[].collision info.surfaces[].flags',[0,1],
        'original diagnostic',source_definition=0,affected_instances=[10,11])
    return bsp, record


def resolve(bsp, record):
    evidence = semantics.collision_evidence(bsp, record)
    result = semantics.report([record],[semantics.collision_flags(evidence)])
    result['records'][0]['provenance'] = dict(source_sha256='a'*64,zone_set='synthetic_slice')
    return result


class BreakableReporting(unittest.TestCase):
    def test_placements_keep_bsp_definition_names_materials_and_distinct_surface_counts(self):
        bsp, record = fixture()
        resolution = resolve(bsp, record)
        report = breakables.report(resolution)
        self.assertEqual((report['original_contract_count'],report['definition_count'],report['placement_count']),(1,1,2))
        self.assertEqual((report['unique_definition_surface_count'],report['placed_surface_count']),(2,4))
        self.assertEqual([r['source_object_name'] for r in report['records']],['?glass_10','?glass_11'])
        for row in report['records']:
            self.assertEqual(row['source_bsp'],bsp['source_tag'])
            self.assertEqual(row['definition_identity'],bsp['source_tag']+'#instanced geometry definitions[0]')
            self.assertEqual(row['semantic'],'BSP_BREAKABLE_SURFACES')
            self.assertEqual(row['whole_instance_damage_state'],'NOT_ESTABLISHED')
            self.assertIsNone(row['scenario_object_tag'])
            self.assertEqual(row['surface_count'],2)
            self.assertEqual(row['source_bsp_sha256'],'a'*64)
            self.assertEqual(row['source_placement']['position'],[row['placement_index'],0,0])
            self.assertEqual(row['collision_materials'][1]['collision_shader'],'synthetic/glass.shader')
            self.assertEqual(row['render_materials'][0]['source_material_slot'],1)
            self.assertEqual(row['render_materials'][0]['source_shader'],'synthetic/glass.shader')
            self.assertTrue(row['still_blocking'])
            self.assertIn('shard/support',row['missing_fact'])
            # Raw indices and an undecoded support field are retained, not guessed.
            self.assertEqual(row['collision_materials'][1]['breakable_surface_set_indices'],[143])
            self.assertIsNone(row['definition_metadata']['breakable surface sets'][0]['supported bitfield'])
        self.assertIn('?glass_11',breakables.markdown(report))

    def test_materialless_breakable_does_not_alias_last_collision_material_or_sky(self):
        bsp, record = fixture()
        row = breakables.report(resolve(bsp,record))['records'][0]
        materialless = row['collision_materials'][0]
        self.assertEqual(materialless['collision_material_index'],-1)
        self.assertEqual(materialless['material_status'],'UNASSIGNED')
        self.assertIsNone(materialless['collision_shader'])
        self.assertIsNone(materialless['source_collision_material'])
        self.assertTrue(row['still_blocking'])

    def test_reordered_surfaces_and_placements_keep_contract_ids_and_report(self):
        bsp, record = fixture()
        before = breakables.report(resolve(bsp,record))
        bsp['environment_semantics']['authoring']['instances'].reverse()
        record['affected'].reverse(); record['affected_instances'].reverse()
        self.assertEqual(breakables.report(resolve(bsp,record)),before)

    def test_missing_or_wrong_placement_cannot_vanish_from_report(self):
        bsp, record = fixture()
        for corruption in ('missing','wrong_definition','duplicate'):
            with self.subTest(corruption=corruption):
                resolution = resolve(bsp,record)
                placements = resolution['records'][0]['target_authoring_plan']['source_evidence']['placements']
                if corruption == 'missing': placements.pop()
                elif corruption == 'duplicate': placements.append(deepcopy(placements[0]))
                else: placements[0]['instance definition'] = 999
                with self.assertRaises(ValueError): breakables.report(resolution)

    def test_nonbreakable_flags_are_excluded_and_unresolved_render_slot_is_explicit(self):
        bsp, record = fixture()
        evidence = semantics.collision_evidence(bsp,record)
        for surface in evidence['collision_surfaces']: surface['flags']=1
        result = semantics.report([record],[semantics.collision_flags(evidence)])
        self.assertEqual(breakables.report(result)['placement_count'],0)
        bsp, record = fixture()
        bsp['environment_semantics']['authoring']['render_meshes'][0]['parts'][0]['render method index']=-1
        row = breakables.report(resolve(bsp,record))['records'][0]
        self.assertIsNone(row['render_materials'][0]['source_shader'])
        self.assertEqual(row['render_materials'][0]['status'],'UNRESOLVED_SOURCE_INDEX')


if __name__ == '__main__':
    unittest.main()

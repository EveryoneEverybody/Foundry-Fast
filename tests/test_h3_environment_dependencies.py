"""Synthetic dependency/stock-binding contracts, without game assets or a cache reader."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment.dependencies import TagInventory, audit, cache_request, shader_usage
from port_environment.paths import digest


SHADER = 'levels/synthetic/tree.shader'
MISSING = 'levels/synthetic/missing_normal'
RUNTIME = 'shaders/synthetic/verified_normal'


def fixture(directory):
    root = Path(directory)/'tags'
    for name in (SHADER, RUNTIME+'.bitmap', 'elsewhere/missing_normal.bitmap'):
        p = root/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'synthetic source, not a proprietary tag')
    manifest = dict(shaders={SHADER:dict(status='resolved_snapshot', group='rmsh',
        categories=[dict(category='bump_mapping', source_index=2, option='detail')],
        authored_parameters=[dict(name='inactive_height', bitmap='levels/synthetic/stale_height')],
        parameters=[dict(name='bump_detail_map', type='bitmap', bitmap=MISSING+'#0', transform=[18,18,0,0]),
                    dict(name='coefficient', type='real', value=1.)])},
        bitmaps={MISSING+'#0':dict(path=MISSING, index=0, status='error'),
                 RUNTIME+'#0':dict(path=RUNTIME, index=0, status='preview', image_count=1)})
    geometry = dict(source_tag='levels/synthetic/bsp.scenario_structure_bsp', bsp_index=2,
        materials=[dict(source_shader=SHADER)],
        objects=[dict(id=0, triangles=[dict(material=0),dict(material=0)]),
                 dict(id=1, triangles=[dict(material=0)])],
        instances=[dict(id=10, object=0, name='tree_a'), dict(id=11, object=0, name='tree_b'),
                   dict(id=12, object=1, name='@CollideOnly')],
        environment_semantics=dict(collision_object=1, collision_materials=[SHADER],
            collision_surfaces=[dict(material=0, source_surface=19)]))
    cache = Path(directory)/'synthetic.map'
    cache.write_bytes(b'Synthetic cache identity only. Reader is not invoked by these tests.')
    record = dict(source_kind='retail_cache', cache=str(cache), bytes=cache.stat().st_size, sha256=digest(cache),
        scenario='levels/synthetic/world', cache_type='MccHalo3U13', reader=dict(mode='read-only'),
        shaders=[dict(name=SHADER.removesuffix('.shader'), id=42,
            categories=[dict(name='bump_mapping', index=2, option='detail')],
            properties=[dict(template='shaders/synthetic/template',
                samplers=[dict(index=0, usage='bump_detail_map', valid=True, bitmap=RUNTIME, group='bitm', tiling_index=0)],
                arguments=[dict(index=0, name='bump_detail_map'),dict(index=1, name='coefficient')],
                constants=[[18,18,0,0],[1,1,1,1]])])])
    selection = dict(source_scenario='levels/synthetic/world.scenario', source_zone_set='authored_slice')
    return manifest, geometry, selection, TagInventory(root), record


class EnvironmentDependencies(unittest.TestCase):
    def test_source_sphere_marker_has_no_render_material_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            _, bsp, _, _, _ = fixture(directory)
            expected = shader_usage([bsp], [])
            bsp['objects'].append(dict(id=2, kind='sphere_marker', radius=1, material=0))
            bsp['instances'].append(dict(id=13, object=2, name='authored_sphere_marker'))
            self.assertEqual(shader_usage([bsp], []), expected)
            self.assertEqual(bsp['objects'][-1]['kind'], 'sphere_marker')

    def test_full_tree_basename_match_is_reported_but_never_substituted(self):
        with tempfile.TemporaryDirectory() as directory:
            m, b, selection, inventory, _ = fixture(directory)
            effective, report = audit(m, [b], [], selection, inventory)
            missing = report['missing_references'][-1]
            self.assertEqual(missing['classification'], 'ACTIVE_REFERENCE_UNRESOLVED')
            self.assertEqual(missing['tree_search']['exact_basename_matches'], ['elsewhere/missing_normal.bitmap'])
            self.assertEqual(effective['shaders'][SHADER]['parameters'][0]['bitmap'], MISSING+'#0')
            self.assertEqual(len(report['unsupported']), 1)
            self.assertEqual(cache_request(m, inventory)['bitmaps'], [MISSING+'.bitmap'])

    def test_verified_runtime_binding_preserves_raw_recipe_and_deduplicates_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            m, b, selection, inventory, record = fixture(directory)
            original = deepcopy(m)
            effective, report = audit(m, [b], [], selection, inventory, [record])
            self.assertEqual(m, original)
            self.assertFalse(report['unsupported'])
            self.assertEqual(list(effective['bitmaps']), [RUNTIME+'#0'])
            self.assertEqual(effective['shaders'][SHADER]['parameters'][0]['bitmap'], RUNTIME+'#0')
            binding = report['runtime_binding_overrides'][0]
            self.assertEqual(report['inventory']['source_kind'], 'loose_h3ek')
            self.assertEqual(binding['source_shader_kind'], 'loose_h3ek')
            self.assertEqual(binding['binding_source_kind'], 'retail_cache')
            self.assertEqual(binding['authoring_bitmap_source_kind'], 'loose_h3ek')
            self.assertEqual(binding['cache_evidence'][0]['source_kind'], 'retail_cache')
            self.assertEqual(binding['original_bitmap'], MISSING+'.bitmap')
            self.assertEqual(binding['authoring_bitmap_sha256'], inventory.source_hash(RUNTIME+'.bitmap'))
            use = report['shader_usage'][SHADER][0]
            self.assertEqual(use['placed_triangles'], 4)
            self.assertEqual(use['triangle_indices'], [0, 1])
            self.assertEqual([p['name'] for p in use['placements']], ['tree_a','tree_b'])
            self.assertEqual(use['source_bsp_index'], 2)

    def test_inactive_and_collision_only_missing_references_do_not_gate_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            m, b, selection, inventory, _ = fixture(directory)
            b['instances'] = [b['instances'][-1]]
            effective, report = audit(m, [b], [], selection, inventory)
            self.assertFalse(report['unsupported'])
            self.assertEqual(report['classification_counts'], {
                'INACTIVE_SHADER_OPTION_REFERENCE':1, 'OUTSIDE_SELECTED_RENDER_USAGE':1})
            self.assertFalse(effective['bitmaps'])
            self.assertEqual(effective['shaders'][SHADER]['parameters'], m['shaders'][SHADER]['parameters'])
            self.assertFalse(cache_request(m, inventory, usage=shader_usage([b], []))['shaders'])

    def test_verified_bump_detail_targets_native_slot_without_changing_uv_or_opacity(self):
        with tempfile.TemporaryDirectory() as directory:
            m, b, selection, inventory, record = fixture(directory)
            m['shaders'][SHADER]['categories'] += [dict(category='alpha_test', source_index=0, option='none'),
                                                 dict(category='blend_mode', source_index=0, option='opaque')]
            record['shaders'][0]['categories'] += [dict(name='alpha_test', index=0, option='none'),
                                                  dict(name='blend_mode', index=0, option='opaque')]
            # Nonzero translations distinguish source UV preservation from a default.
            uv = [18., 7., .25, -.5]
            m['shaders'][SHADER]['parameters'][0]['transform'] = uv
            record['shaders'][0]['properties'][0]['constants'][0] = uv
            original = deepcopy(m)
            effective, report = audit(m, [b], [], selection, inventory, [record])
            self.assertFalse(report['unsupported'])
            override = report['runtime_binding_overrides'][0]
            target = override['target_authoring_plan']
            self.assertEqual(target['target_parameter'], 'bump_detail_map')
            self.assertEqual(target['parameter_binding']['bitmap'], RUNTIME+'#0')
            self.assertEqual(target['parameter_binding']['transform'], uv)
            self.assertFalse(target['distinct_detail_bitmap_required'])
            self.assertEqual(target['image_usage'], 'Detail Normal Map')
            self.assertEqual(target['target_tag_group'], 'shader')
            self.assertEqual(override['original_parameter'], original['shaders'][SHADER]['parameters'][0])
            self.assertEqual(effective['shaders'][SHADER]['categories'], original['shaders'][SHADER]['categories'])
            self.assertEqual(m, original)

    def test_out_of_zone_cache_cannot_override_selected_mission(self):
        with tempfile.TemporaryDirectory() as directory:
            m, b, selection, inventory, record = fixture(directory)
            record['scenario'] = 'levels/synthetic/different_mission'
            _, report = audit(m, [b], [], selection, inventory, [record])
            self.assertEqual(report['cache_evidence_status'], 'NO_MATCHING_SCENARIO_EVIDENCE')
            self.assertTrue(report['unsupported'])

    def test_incomplete_shader_walk_cannot_classify_authored_reference_as_inactive(self):
        with tempfile.TemporaryDirectory() as directory:
            m, b, selection, inventory, record = fixture(directory)
            m['shaders'][SHADER]['status'] = 'error'
            _, report = audit(m, [b], [], selection, inventory, [record])
            self.assertEqual(report['missing_references'][0]['classification'], 'UNRESOLVED_SHADER_PARAMETER_USAGE')
            self.assertTrue(any(r['source_field'] == 'authored bitmap parameter usage' for r in report['unsupported']))

    def test_stale_cache_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            m, b, selection, inventory, record = fixture(directory)
            Path(record['cache']).write_bytes(b'changed cache')
            with self.assertRaisesRegex(ValueError, 'cache bytes'):
                audit(m, [b], [], selection, inventory, [record])

    def test_cache_evidence_cannot_be_mislabeled_as_loose_source_or_omit_provenance(self):
        for kind in ('loose_h3ek', 'installed_other_game_cache', None):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                m, b, selection, inventory, record = fixture(directory)
                if kind is None:
                    del record['source_kind']
                else:
                    record['source_kind'] = kind
                with self.assertRaisesRegex(ValueError, 'source_kind=retail_cache'):
                    audit(m, [b], [], selection, inventory, [record])

    def test_mismatched_options_uvs_constants_sampler_or_image_never_override(self):
        for change in ('category','uv','constant','sampler','image','group','duplicate_sampler'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                m, b, selection, inventory, record = fixture(directory)
                shader = record['shaders'][0]
                props = shader['properties'][0]
                if change == 'category': shader['categories'][0]['index'] = 0
                elif change == 'uv': props['constants'][0][0] = 19
                elif change == 'constant': props['constants'][1] = [0,0,0,0]
                elif change == 'sampler': props['samplers'][0]['usage'] = 'wrong_map'
                elif change == 'image': m['bitmaps'][RUNTIME+'#0']['image_count'] = 2
                elif change == 'group': props['samplers'][0]['group'] = 'rmsh'
                else: props['samplers'].append(deepcopy(props['samplers'][0]))
                effective, report = audit(m, [b], [], selection, inventory, [record])
                self.assertTrue(report['unsupported'])
                self.assertFalse(report['runtime_binding_overrides'])
                self.assertEqual(effective['shaders'][SHADER]['parameters'][0]['bitmap'], MISSING+'#0')

    def test_cache_that_still_needs_absent_pixels_reports_recovery_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            m, b, selection, inventory, record = fixture(directory)
            record['shaders'][0]['properties'][0]['samplers'][0]['bitmap'] = MISSING
            _, report = audit(m, [b], [], selection, inventory, [record])
            self.assertTrue(report['unsupported'])
            self.assertIn('pixel recovery remains necessary', report['missing_references'][-1]['cache_checks'][0]['reason'])

    def test_conflicting_same_scenario_cache_evidence_does_not_choose_arbitrarily(self):
        with tempfile.TemporaryDirectory() as directory:
            m, b, selection, inventory, record = fixture(directory)
            conflicting = deepcopy(record)
            conflicting['shaders'][0]['properties'][0]['constants'][0][0] = 99
            _, report = audit(m, [b], [], selection, inventory, [record, conflicting])
            self.assertTrue(report['unsupported'])
            self.assertFalse(report['runtime_binding_overrides'])


if __name__ == '__main__':
    unittest.main()

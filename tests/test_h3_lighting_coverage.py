"""Readiness must retain all known unresolved contracts, not only emitters."""
import sys
import unittest
from pathlib import Path
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry/h3_import'))
from port_environment.lighting_coverage import source_coverage_gaps, scenario_recipe_gaps


class CoverageTests(unittest.TestCase):
    def test_all_nonzero_bsp_fields_are_reported(self):
        rows = source_coverage_gaps({}, {'flags': '64', 'cloned bsp flags': '16'}, bsp_index=7)
        self.assertEqual([r['source_value'] for r in rows], ['64', '16'])
        self.assertTrue(all(r['bsp_index'] == 7 for r in rows))

    def test_zero_fields_do_not_invent_a_mismatch(self):
        self.assertEqual(source_coverage_gaps({}, {'flags': '0', 'cloned bsp flags': '0'}), [])

    def test_shared_definition_is_distinct_from_material_density(self):
        bsp = {'authoring': {'instances': [dict(source_index=42, **{'lightmapping policy': {'name': 'per-pixel shared'}})]}}
        before = deepcopy(bsp)
        self.assertEqual(source_coverage_gaps(bsp)[0]['source_instances'], [42])
        self.assertEqual(bsp, before)

    def test_per_vertex_and_probe_do_not_invent_definition_atlas_requests(self):
        bsp = {'authoring': {'instances': [{'lightmapping policy': {'name': n}} for n in ['per-vertex', 'single-probe']]}}
        self.assertEqual(source_coverage_gaps(bsp), [])

    def test_three_bound_recipes_remain_unknown_and_unbound_is_separate(self):
        def field(name, value): return dict(element='field', attributes=dict(name=name, value=value))
        rows = [dict(source_index=i, fields=[field('type', p), field('type', shape),
                field('lightmap light scale', '0'), field('lightmap type', 'use light tag setting')])
                for i, (p, shape) in enumerate([(',-1', 'frustum'), (',3', 'sphere'), (',3', 'frustum'), (',3', 'frustum')])]
        before = deepcopy(rows)
        issues = scenario_recipe_gaps({'placements': rows})
        self.assertEqual([r['source_placement'] for r in issues], [1, 2, 3])
        self.assertTrue(all('do not prove no contribution' in r['reason'] for r in issues))
        self.assertEqual(rows, before)

    def test_missing_binding_is_not_a_pass(self):
        self.assertTrue(scenario_recipe_gaps({'placements': [{'fields': []}]}))


if __name__ == '__main__': unittest.main()

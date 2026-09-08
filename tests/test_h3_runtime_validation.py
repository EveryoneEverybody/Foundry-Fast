"""Runtime evidence cannot be inferred from native build success."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment import runtime_validation as runtime


class RuntimeEvidenceTests(unittest.TestCase):
    def observation(self, check='visible', status='RUNTIME_PASS'):
        return dict(fixture_id='crates:8', check=check, status=status, fixture_sha256='fixture',
            scenario_sha256='scenario', basis='NATE_MANUAL', observer='Nate',
            observed_at='2026-09-08T16:00:00+00:00', evidence='Shot the selected block; it visibly moved')

    def fixture(self):
        return dict(id='crates:8', fixture_sha256='fixture', runtime_status=runtime.PENDING,
            checks={k:dict(status=runtime.PENDING, observations=[]) for k in runtime.CHECKS['crates']})

    def test_partial_visible_proof_cannot_accept_physics_or_whole_fixture(self):
        original = self.fixture()
        result = runtime.apply_observations([original], [self.observation()], 'scenario')[0]
        self.assertEqual(result['runtime_status'], runtime.PENDING)
        self.assertEqual(result['checks']['physical_response']['status'], runtime.PENDING)
        self.assertEqual(original['checks']['visible']['status'], runtime.PENDING)

    def test_build_receipts_cannot_be_runtime_evidence(self):
        obs = self.observation(); obs['basis'] = 'TOOL_COMPILED'
        with self.assertRaisesRegex(ValueError, 'never a build receipt'):
            runtime.apply_observations([self.fixture()], [obs], 'scenario')

    def test_stale_scenario_and_fixture_evidence_are_rejected(self):
        for key in ('scenario_sha256', 'fixture_sha256'):
            with self.subTest(key=key):
                obs = self.observation(); obs[key] = 'old bytes'
                with self.assertRaisesRegex(ValueError, 'different fixture/scenario'):
                    runtime.apply_observations([self.fixture()], [obs], 'scenario')

    def test_failure_is_retained_and_all_checks_required_for_pass(self):
        observations = [self.observation(k) for k in runtime.CHECKS['crates']]
        self.assertEqual(runtime.apply_observations([self.fixture()], observations, 'scenario')[0]['runtime_status'], 'RUNTIME_PASS')
        observations[-1]['status'] = 'RUNTIME_FAIL'
        self.assertEqual(runtime.apply_observations([self.fixture()], observations, 'scenario')[0]['runtime_status'], 'RUNTIME_FAIL')

    def test_duplicate_results_cannot_silently_overwrite_failure(self):
        with self.assertRaisesRegex(ValueError, 'Conflicting/repeated'):
            runtime.apply_observations([self.fixture()], [self.observation(status='RUNTIME_FAIL'), self.observation()], 'scenario')

    def test_observation_requires_attribution_and_concrete_evidence(self):
        for key in ('evidence', 'observer'):
            obs = self.observation(); obs[key] = ''
            with self.assertRaisesRegex(ValueError, 'observer and concrete evidence'):
                runtime.apply_observations([self.fixture()], [obs], 'scenario')

    def test_spawn_policy_uses_source_flag_names_not_native_bit_positions(self):
        field = dict(name='placement flags', value='4096', set_flags=['not automatically'])
        row = dict(source_records=[field])
        self.assertIn('not automatically', runtime.placement_flags(row))
        field['set_flags'] = []
        with self.assertRaisesRegex(ValueError, 'named flag evidence'):
            runtime.placement_flags(row)

    def test_duplicate_palette_entries_count_each_placement_once(self):
        t = dict(families={f:dict(palette=[], placements=[]) for f in runtime.CHECKS})
        t['families']['crates'] = dict(palette=[dict(source_index=2, source_tag='crate'), dict(source_index=9, source_tag='crate')],
            placements=[dict(source_palette_index=2), dict(source_palette_index=9), dict(source_palette_index=99)])
        blockers = [dict(source_tag='crate', stage='NATIVE', reason='Physics shape requires an unambiguous source body association')]
        result = runtime.blocker_yield(t, blockers)
        self.assertEqual(result[0]['affected_source_placements'], 2)
        self.assertEqual(result[0]['root_count'], 1)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            runtime.blocker_yield(t, blockers*2)


if __name__ == '__main__':
    unittest.main()

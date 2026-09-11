"""All-BSP coverage must not stop at the first source rejection."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from preflight_h3_lighting import census, variants


class LightingPreflight(unittest.TestCase):
    def test_variants_preserve_count_and_every_owner(self):
        result = variants([(0, 'a', {'flags': 1}), (2, 'b', {'flags': 1}), (2, 'b', {'flags': 1})])
        self.assertEqual(result, [dict(source_value={'flags': 1}, count=3, bsps=[0, 2], sources=['a', 'b'])])

    def fixture(self):
        source = {'flags': '1', 'frustum blend': '0.5', 'emissive power': '1',
                  'attenuation falloff': '1', 'attenuation cutoff': '2'}
        return dict(materials=[], bsps=[dict(materials=[dict(slot=0, source_shader='test.shader', lighting=source)],
                    authoring=dict(materials=[{}])) for _ in range(3)],
                    lighting_by_bsp=[dict(definitions=[], source_tag='test',
                    source_semantics=dict(light_definitions=[], materials=[source])) for _ in range(3)])

    def test_reports_all_bsps_and_retains_source_fields(self):
        report = census(self.fixture())
        self.assertEqual([r['bsp_index'] for r in report['bsps']], [0, 1, 2])
        self.assertTrue(all(r['status'] == 'STATIC_BLOCKED' for r in report['bsps']))
        self.assertEqual(report['surface_variants'][0]['count'], 3)
        self.assertEqual(report['native_preparation'], 'NOT_RUN')

    def test_truncated_lighting_list_is_not_a_partial_pass(self):
        plan = self.fixture(); plan['lighting_by_bsp'].pop()
        with self.assertRaises(ValueError): census(plan)

    def test_dropped_unknown_generic_enum_is_reported(self):
        plan = self.fixture()
        plan['lighting_by_bsp'][2]['source_semantics']['light_definitions'] = [dict(type='unrecognized', shape='circle', flags='0')]
        reasons = [r['reason'] for r in census(plan)['bsps'][2]['issues']]
        self.assertIn('Unsupported source generic light type, shape or flags', reasons)
        self.assertIn('Source generic definitions were omitted from authoring', reasons)


if __name__ == '__main__':
    unittest.main()

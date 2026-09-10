from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment.sun_diagnostic import sun_view, assert_sun_delta


def xml(rgb=(4, 2, 1), vertex=7):
    values = (0, 0, 1, *rgb)
    return ('<tag group="render_model"><array name="sun">' + ''.join(
        f'<element index="{i}"><field name="value" type="real" value="{v}"/></element>'
        for i, v in enumerate(values)) + f'</array><field name="vertex" value="{vertex}"/></tag>').encode()


class SunDiagnosticTests(unittest.TestCase):
    def test_view_changes_only_analytic_irradiance(self):
        plan = dict(skies=[dict(destination='sky.scenery', lighting=dict(
            sun_irradiance=[4,2,1], source_samples=[dict(intensity=[1,1,1])]))],
            bsps=['accepted'], lighting_by_bsp=['accepted'])
        original = deepcopy(plan)
        view, path, values = sun_view(plan, 0, .25)
        self.assertEqual(plan, original)
        self.assertEqual((path, values), ('sky.render_model', [1,.5,.25]))
        expected = deepcopy(plan); expected['skies'][0]['lighting']['sun_irradiance'] = values
        self.assertEqual(view, expected)
        for factor in (0, 1, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError): sun_view(plan, 0, factor)

    def test_xml_rejects_changed_sky_geometry_or_unscaled_sun(self):
        self.assertEqual(assert_sun_delta(xml(), xml((1,.5,.25)), .25)['status'], 'SUN_IRRADIANCE_ONLY')
        for bad in (xml((1,.5,.25), 8), xml((1,.5,.3)), xml()):
            with self.assertRaises(ValueError): assert_sun_delta(xml(), bad, .25)


if __name__ == '__main__':
    unittest.main()

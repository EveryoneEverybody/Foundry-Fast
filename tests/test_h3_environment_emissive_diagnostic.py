from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment.emissive_diagnostic import material_power_view, assert_material_power_delta


def fixture():
    row = dict(source_shader='fixture.shader', source_lighting_index=83, lighting={'emissive power': '3.2', 'emissive color': '1,1,1'})
    plan = dict(bsps=[dict(source_index=1, destination='slice.bsp', materials=[row])],
                lighting_by_bsp=[dict(definitions=[dict(intensity=4)], instances=[dict(origin=[1,2,3])])], skies=['accepted'])
    native = dict(status='VERIFIED_BEFORE_FAUX', bsps=[dict(bsp='slice.bsp', emissive=[dict(
        source_material=0, source_shader='fixture.shader', native_material_info_indices=[3])])])
    return plan, native


def xml(power='3.2', intensity='4', color='1,1,1'):
    return f'''<tag group="scenario_structure_lighting_info">
    <block name="material info" value="rows,1"><element index="0">
    <field name="emissive power" value="{power}" type="real"/>
    <field name="emissive color" value="{color}" type="real rgb color"/>
    <field name="attenuation cutoff" value="2" type="real"/>
    </element></block><block name="generic light definitions" value="defs,1"><element index="0">
    <field name="intensity" value="{intensity}" type="real"/>
    </element></block><block name="generic light instances" value="instances,0"/></tag>'''.encode()


class MaterialDiagnosticTests(unittest.TestCase):
    def test_material_power_does_not_change_generic_lights_or_source(self):
        plan, native = fixture(); original = deepcopy(plan)
        view, index, rows, bindings = material_power_view(plan, 1, [0], 25., native)
        self.assertEqual(plan, original)
        self.assertEqual(index, 0); self.assertEqual(rows, [3])
        self.assertEqual(bindings[0]['baseline_power'], 3.2)
        self.assertEqual(view['lighting_by_bsp'], plan['lighting_by_bsp'])
        expected = deepcopy(plan); expected['bsps'][0]['materials'][0]['lighting']['emissive power'] = '25.0'
        self.assertEqual(view, expected)

    def test_rejects_unselected_alias_of_deduplicated_material(self):
        plan, native = fixture()
        plan['bsps'][0]['materials'].append(deepcopy(plan['bsps'][0]['materials'][0]))
        native['bsps'][0]['emissive'].append(dict(native['bsps'][0]['emissive'][0], source_material=1))
        with self.assertRaisesRegex(ValueError, 'unselected'):
            material_power_view(plan, 1, [0], 25., native)
        self.assertEqual(material_power_view(plan, 1, [0,1], 25., native)[2], [3])

    def test_invalid_selection_and_power_fail_closed(self):
        for slots, power in [([],25),([0,0],25),([8],25),([0],float('nan')),([0],0),([0],3.2),([0],101)]:
            with self.subTest(slots=slots,power=power), self.assertRaises(ValueError):
                p,n=fixture(); material_power_view(p,1,slots,power,n)

    def test_complete_native_readback_allows_only_material_power(self):
        self.assertEqual(assert_material_power_delta(xml(), xml('25'), [0], 25)['status'], 'MATERIAL_POWER_ONLY')
        for bad in [xml('25','40'), xml('25',color='1,0,0'), xml(), xml('25').replace(b'value="2"', b'value="200"')]:
            with self.assertRaises(ValueError):assert_material_power_delta(xml(), bad, [0], 25)


if __name__ == '__main__':
    unittest.main()

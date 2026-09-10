import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('h3_tint_order', Path(__file__).parents[1]/'tools/h3_tint_order.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TintOrderTests(unittest.TestCase):
    def test_reference_edit_preserves_every_other_byte(self):
        data = bytes(range(256))+b'shaders\\shader\0'+bytes(range(255, -1, -1))+b'shaders\\shader_templates\\_0_2_0_1_2_0_0_0_0_0_0_0'
        output = module.redirect(data, 'h3tint')
        self.assertEqual(len(output), len(data))
        self.assertEqual(output.replace(b'shaders\\h3tint', b'shaders\\shader'), data)

    def test_unknown_reference_layout_fails_closed(self):
        for data in (b'', b'shaders\\shader', b'shaders\\shader'*3):
            with self.assertRaises(ValueError):
                module.redirect(data, 'h3tint')
        for alias in ('shader', '../bad', 'toolong', 'ABCDEF'):
            with self.assertRaises(ValueError):
                module.redirect(b'shaders\\shader'*2, alias)

    def test_source_drift_and_duplicate_expression_fail_closed(self):
        for source in ('different source', module.STOCK*2):
            with self.assertRaises(ValueError):
                module.replace_once(source, module.STOCK, module.H3_ORDER)

    def test_h3_endpoint_and_difference_across_material_domain(self):
        for a in (0.0, .07, .4, 1.0):
            for n in (.1, 1.0):
                for g in (.2, 1.0):
                    for b in (0.0, .3, 1.0):
                        for f in (0.0, .1, .7, 1.0):
                            h3 = (1-b)*((1-f)*n+f*g)+b*a
                            reach = (1-f)*((1-b)*n+b*a)+f*g
                            self.assertAlmostEqual(reach-h3, b*f*(g-a))
                            if b == 1:
                                self.assertAlmostEqual(h3, a)
                            if f == 1:
                                self.assertAlmostEqual(reach, g)


if __name__ == '__main__':
    unittest.main()

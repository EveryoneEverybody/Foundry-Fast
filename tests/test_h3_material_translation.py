"""Pure semantic, corpus and writer-contract regressions. No Blender or tag I/O."""
import copy
import ast
from dataclasses import FrozenInstanceError
import importlib
import json
import math
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
NAME = 'h3_semantic_tests'
package = ModuleType(NAME)
package.__path__ = [str(ROOT/'blender/addons/io_scene_foundry/h3_import')]
sys.modules[NAME] = package
m = importlib.import_module(NAME+'.material_translation')
w = importlib.import_module(NAME+'.material_writer')
c = importlib.import_module(NAME+'.material_census')
FIXTURES = ROOT/'tests/fixtures/h3_rmsh_translation'


def vectors(name):
    return json.loads((FIXTURES/f'voi_{name}_2026-09-09.json').read_text(encoding='utf-8'))


def resolved(vector):
    values = dict(vector['source'])
    if vector['source_categories']['material_model'] == 'single_lobe_phong':
        # Numerical single-lobe vectors omit tint. Use a deliberately nonwhite
        # synthetic tint to test equal endpoint preservation independently.
        values['specular_tint'] = [.2, .4, .7, 1.0]
    return dict(source=vector['source_shader'], group='rmsh', status='resolved_snapshot',
                definition='shaders/shader.render_method_definition',
                categories=[dict(category=k, option=v, source_index=i)
                            for i, (k, v) in enumerate(vector['source_categories'].items())],
                parameters=[dict(name=k, type='color' if isinstance(v, list) else 'real',
                                 value=v, origin='authored', has_functions=False)
                            for k, v in values.items() if v is not None])


def translated(raw):
    return m.translate(m.H3MaterialRecord.from_resolved(raw))


def scalar(raw, name, value):
    for p in raw['parameters']:
        if p['name'] == name:
            p['value'] = value
            return
    raw['parameters'].append(dict(name=name, type='real', value=value))


class TranslationContracts(unittest.TestCase):
    def setUp(self):
        self.single = resolved(vectors('single_lobe_regression_vectors')[1])
        self.two = resolved(vectors('two_lobe_selected_fixtures')[0])

    def test_deeply_immutable_source_and_target(self):
        source = m.H3MaterialRecord.from_resolved(self.single)
        with self.assertRaises(FrozenInstanceError): source.source_shader = 'changed'
        with self.assertRaises(TypeError): source.parameters['roughness']['value'] = 5
        with self.assertRaises(TypeError): source.raw_record['categories'][0]['option'] = 'changed'
        plan = m.translate(source)
        with self.assertRaises(TypeError): plan.payload['parameters']['roughness']['value'] = 5
        exported = plan.to_dict()
        exported['parameters']['roughness']['value'] = 5
        self.assertNotEqual(plan.semantic_values()['roughness'], 5)
        self.single['parameters'][0]['value'] = 99
        self.assertNotEqual(source.parameters[self.single['parameters'][0]['name']]['value'], 99)

    def test_single_lobe_tint_repacked_with_equal_endpoints(self):
        angle = translated(self.single).semantic_values()['specular_color_by_angle']
        self.assertEqual(angle['color0_normal'], [.2, .4, .7, 1])
        self.assertEqual(angle['color0_normal'], angle['color1_glancing'])

    def test_single_only_normalization_and_common_fold_once(self):
        for raw in (self.single, self.two):
            for name, value in [('specular_coefficient', .5), ('analytical_specular_contribution', 1),
                                ('area_specular_contribution', .1), ('environment_map_specular_contribution', .5)]:
                scalar(raw, name, value)
        a, b = translated(self.single).semantic_values(), translated(self.two).semantic_values()
        self.assertAlmostEqual(a['analytical_specular_contribution'], .5*a['roughness']**4*math.pi**2)
        self.assertEqual(b['analytical_specular_contribution'], .5)
        for p in (a, b):
            self.assertEqual(p['specular_coefficient'], 1)
            self.assertAlmostEqual(p['area_specular_contribution'], .05/math.pi)
            self.assertEqual(p['environment_map_specular_contribution'], .25)
            self.assertEqual(p['analytical_roughness'], p['roughness'])

    def test_power_clamps_and_directional_noninverse(self):
        self.assertEqual(m.power_to_roughness(-5), m.power_to_roughness(.01))
        self.assertEqual(m.power_to_roughness(9000), m.power_to_roughness(2000))
        self.assertAlmostEqual(m.power_to_roughness(20), .14165536102041346)
        self.assertAlmostEqual(m.roughness_to_compatibility_power(.1), .272909999*.1**-1.3973)
        self.assertNotAlmostEqual(m.roughness_to_compatibility_power(m.power_to_roughness(20)), 20)
        for bad in (float('nan'), float('inf'), True):
            with self.assertRaises(ValueError): m.power_to_roughness(bad)

    def test_asphalt_runtime_fixture_is_generic_equations(self):
        expected = dict(specular_coefficient=1, analytical_specular_contribution=.00049348,
                        area_specular_contribution=.0159155, environment_map_specular_contribution=.25,
                        roughness=.1, analytical_roughness=.1, env_roughness_scale=.1, env_roughness_offset=.455)
        actual = translated(self.single).semantic_values()
        for k, v in expected.items(): self.assertAlmostEqual(actual[k], v, delta=1e-7)
        self.single['source'] = 'arbitrary/not_voi.shader'
        self.assertEqual(actual, translated(self.single).semantic_values())

    def test_missing_inputs_do_not_use_defaults(self):
        self.two['parameters'] = [p for p in self.two['parameters'] if p['name'] != 'normal_specular_power']
        self.assertEqual(translated(self.two).status, m.UNRESOLVED)

    def test_nonconstant_and_input_functions_never_flattened(self):
        for header, name in [('03', ''), ('01', 'object_state'), ('01', '')]:
            raw = copy.deepcopy(self.single)
            p = next(p for p in raw['parameters'] if p['name'] == 'roughness')
            p['has_functions'] = True
            data = header + ('25' if not name and header == '01' else '24') + '00'*30
            raw['authored_parameters'] = [dict(name='roughness', functions=[dict(function_hex=data, input=name)])]
            self.assertEqual(translated(raw).status, m.UNRESOLVED)

    def test_constant_function_uses_effective_value_and_keeps_bytes(self):
        p = next(p for p in self.single['parameters'] if p['name'] == 'roughness')
        p['has_functions'] = True
        self.single['authored_parameters'] = [dict(name='roughness', functions=[dict(function_hex='0124'+'00'*30)])]
        source = m.H3MaterialRecord.from_resolved(self.single)
        self.assertEqual(source.parameters['roughness']['function_state'], 'CONSTANT_FUNCTION')
        self.assertEqual(m.translate(source).status, m.TRANSLATED)
        self.assertEqual(source.parameters['roughness']['functions'][0]['function_hex'], '0124'+'00'*30)

    def test_function_flag_without_bytes_fails_closed(self):
        self.single['parameters'][0]['has_functions'] = True
        self.assertEqual(translated(self.single).status, m.UNRESOLVED)

    def test_unknown_extern_and_known_renderer_provider(self):
        self.single['parameters'].append(dict(name='dynamic_environment_map_0', type='bitmap', extern='dynamic environment map 1'))
        plan = translated(self.single)
        self.assertEqual(plan.status, m.TRANSLATED)
        self.assertEqual(plan.payload['compatibility_inputs']['dynamic_environment_map_0']['type'], 'extern')
        self.single['parameters'][-1]['extern'] = 'unknown provider'
        self.assertEqual(translated(self.single).status, m.UNRESOLVED)

    def test_unknown_families_and_options_fail_closed(self):
        for model in ('cook_torrance', 'foliage', 'glass', 'organism', 'mcc_pbr', 'new_model'):
            raw = copy.deepcopy(self.two)
            next(c for c in raw['categories'] if c['category'] == 'material_model')['option'] = model
            plan = translated(raw)
            self.assertIsNone(plan.rule_id)
            self.assertEqual(plan.status, m.UNRESOLVED)
            self.assertEqual(plan.to_dict()['parameters'], {})
        for group in ('rmtr', 'rmfl', 'rmhg', 'rmgl'):
            self.assertEqual(translated(dict(self.two, group=group)).status, m.UNRESOLVED)
        self.assertEqual(translated(dict(self.two, source='unrelated.shader_glass')).status, m.UNRESOLVED)
        self.two['categories'].append(dict(category='future_option', option='default'))
        self.assertEqual(translated(self.two).status, m.UNRESOLVED)

    def test_diffuse_and_none_never_emit_specular_controls(self):
        for model in ('diffuse_only', 'none'):
            raw = copy.deepcopy(self.single)
            next(c for c in raw['categories'] if c['category'] == 'material_model')['option'] = model
            plan = translated(raw)
            self.assertEqual(plan.status, m.TRANSLATED)
            self.assertEqual(plan.payload['options']['material_model'], model)
            self.assertFalse(m.SPECULAR_INPUTS.intersection(plan.payload['parameters']))

    def test_glancing_is_separate_and_writer_rejects_before_io(self):
        plan = translated(self.two)
        self.assertEqual(plan.status, m.TRANSLATED)
        self.assertNotIn('glancing_roughness', plan.payload['parameters'])
        self.assertIn('glancing_roughness', plan.payload['compatibility_inputs'])
        with self.assertRaisesRegex(ValueError, 'glancing_roughness'): w.require_writable(plan)
        damaged = plan.to_dict()
        damaged['compatibility_inputs'].clear()
        with self.assertRaisesRegex(ValueError, 'glancing_roughness'): w.require_writable(damaged)

    def test_angle_rgb_snapshot_rejected(self):
        plan = translated(self.single).to_dict()
        plan['parameters']['specular_color_by_angle']['type'] = 'color'
        with self.assertRaisesRegex(ValueError, 'angle-color'): w.require_writable(plan)

    def test_writer_rejects_wrong_or_changed_source(self):
        plan = translated(self.single)
        w.require_source(plan, self.single)
        changed = copy.deepcopy(self.single)
        changed['parameters'][0]['value'] = 99
        with self.assertRaisesRegex(ValueError, 'changed H3 source'): w.require_source(plan, changed)
        with self.assertRaisesRegex(ValueError, 'changed H3 source'): w.require_source(plan, self.two)

    def test_real_shader_entry_disables_autosave_on_rejection(self):
        # Execute the actual entry method with a tag double, avoiding Blender
        # imports. This covers the existing Tag.__exit__ save-on-error hazard.
        path = ROOT/'blender/addons/io_scene_foundry/managed_blam/shader.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ShaderTag')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_write_h3_semantic_tag')
        namespace = {'__package__': NAME+'.managed_blam'}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
        aliases = {NAME+'.h3_import':package, NAME+'.h3_import.material_writer':w}
        with patch.dict(sys.modules, aliases):
            for material in ({'h3_reach_staged':True},
                             {'h3_reach_authoring_plan':json.dumps(translated(self.two).to_dict())},
                             {'h3_reach_authoring_plan':json.dumps(translated(self.single).to_dict())}):
                tag = SimpleNamespace(tag_has_changes=True, always_save=True, corinth=False,
                    _find_group_node=lambda material:object(), _group_node_matches=lambda node:True)
                with patch.object(w, 'apply_plan', side_effect=ValueError('writer failed')):
                    with self.assertRaises(ValueError): namespace[method.name](tag, material, True)
                self.assertFalse(tag.tag_has_changes)
                self.assertFalse(tag.always_save)

    def test_bitmap_sampler_uv_and_provenance_retained(self):
        p = dict(name='base_map', type='bitmap', bitmap='test#2', sampler=dict(address_x='clamp', address_y='mirror', filter='point'),
                 transform=[2, 3, 4, 5], channels=dict(alpha='specular mask'), origin='rmop_default')
        self.single['parameters'].append(p)
        source = m.H3MaterialRecord.from_resolved(self.single, {'test#2':dict(path='test', index=2)}, {'source_sha256':'test hash'})
        plan = m.translate(source)
        out = plan.to_dict()['parameters']['base_map']
        for key in ('bitmap', 'sampler', 'transform', 'channels'): self.assertEqual(out[key], p[key])
        self.assertEqual(source.parameters['base_map']['origin'], 'rmop_default')
        self.assertEqual(out['origin'], 'H3_DIRECT')
        self.assertEqual(source.bitmaps['test#2']['index'], 2)
        self.assertEqual(source.provenance['source_sha256'], 'test hash')

    def test_census_deduplicates_closure_and_keeps_usage(self):
        raw = self.single
        path = raw['source']
        manifest = dict(source_tag='synthetic.scenario', shaders={path:raw})
        plan = dict(materials=[dict(source_shader=path)]*3,
                    source_dependencies=dict(shader_usage={path:[dict(kind='selected_bsp_render',placed_triangles=4000)]}))
        before = copy.deepcopy((manifest, plan))
        report = c.census(manifest, plan)
        self.assertEqual(report['unique_materials'], 1)
        self.assertEqual(report['records'][0]['usage']['render_triangles'], 4000)
        self.assertEqual((manifest, plan), before)
        self.assertEqual(report, c.census(manifest, plan))

    def test_translator_rejects_target_as_source(self):
        with self.assertRaises(TypeError): m.translate(translated(self.single))

    def test_duplicate_parameter_rejected(self):
        self.single['parameters'].append(self.single['parameters'][0])
        with self.assertRaises(ValueError): m.H3MaterialRecord.from_resolved(self.single)

    def test_duplicate_authored_entries_preserve_all_functions(self):
        self.single['authored_parameters'] = [dict(name='roughness', functions=[dict(function_hex=code+'00'*30)])
                                             for code in ('0124', '0324')]
        source = m.H3MaterialRecord.from_resolved(self.single)
        self.assertEqual(len(source.parameters['roughness']['functions']), 2)
        self.assertEqual(m.translate(source).status, m.UNRESOLVED)

    def test_composite_writer_and_readback_preserve_distinct_endpoints(self):
        class Editor:
            def __init__(self): self.colors = {}; self.exponent = self.minimum = self.maximum = None
            def SetColor(self, i, color): self.colors[i] = color
            def GetColor(self, i): return self.colors[i]
            def SetExponent(self, i, v): self.exponent = v
            def GetExponent(self, i): return self.exponent
            def SetAmplitudeMin(self, i, v): self.minimum = v
            def GetAmplitudeMin(self, i): return self.minimum
            def SetAmplitudeMax(self, i, v): self.maximum = v
            def GetAmplitudeMax(self, i): return self.maximum
        class Function:
            def __init__(self): self.type = SimpleNamespace(Value=0); self.editor = Editor()
            def SelectField(self, name): return self.type if name == 'type' else SimpleNamespace(Value=self.editor)
        class Block:
            def __init__(self): self.Elements = []
            def RemoveAllElements(self): self.Elements.clear()
            def AddElement(self):
                f = Function(); self.Elements.append(f); return f
        block = Block()
        element = SimpleNamespace(SelectField=lambda name: block)
        tag = SimpleNamespace(function_parameters='animated parameters', animated_function='animation function',
            _setup_parameter=lambda *a: element, _set_animated_parameter_type=lambda f, v: setattr(f.type, 'Value', v),
            _FunctionEditorMasterType=int, _FunctionEditorColorGraphType=int)
        p = translated(self.two).to_dict()['parameters']['specular_color_by_angle']
        factory = lambda c: SimpleNamespace(ColorMode=0, Red=c[0], Green=c[1], Blue=c[2], Alpha=c[3])
        result = w.write_angle_color(tag, p, factory)
        w.verify_angle_color(tag, p, result)
        editor = block.Elements[0].editor
        self.assertNotEqual(editor.GetColor(0).Red, editor.GetColor(1).Red)
        editor.colors[0], editor.colors[1] = editor.colors[1], editor.colors[0]
        with self.assertRaises(ValueError): w.verify_angle_color(tag, p, result)
        editor.colors[0], editor.colors[1] = editor.colors[1], editor.colors[0]
        editor.exponent = 999
        with self.assertRaises(ValueError): w.verify_angle_color(tag, p, result)


class SelectedVectors(unittest.TestCase):
    pass


class AllVectors(unittest.TestCase):
    pass


def vector_test(vector):
    def test(self):
        raw = resolved(vector)
        before = json.dumps(raw, sort_keys=True)
        source = m.H3MaterialRecord.from_resolved(raw)
        plan = m.translate(source)
        self.assertEqual(plan.status, m.TRANSLATED, plan.to_dict()['diagnostics'])
        self.assertEqual(json.dumps(raw, sort_keys=True), before)
        self.assertEqual(m.canonical_json(plan.payload), m.canonical_json(m.translate(source).payload))
        self.assertEqual(m.canonical_json(source.raw_record), m.canonical_json(raw))
        expected = vector.get('expected_reach_authoring_plan', vector.get('expected_reach_migration_core'))
        actual = plan.semantic_values()
        def check(a, b):
            if isinstance(b, dict):
                for k, v in b.items(): check(a[k], v)
            elif isinstance(b, list):
                self.assertEqual(len(a), len(b))
                for x, y in zip(a, b): check(x, y)
            elif isinstance(b, (int, float)):
                self.assertAlmostEqual(a, b, delta=max(1e-12, abs(b)*1e-10))
            else: self.assertEqual(a, b)
        check(actual, expected)
    return test


for i, vector in enumerate(vectors('two_lobe_selected_fixtures')):
    setattr(SelectedVectors, f'test_selected_{i:03}', vector_test(vector))
for family in ('single_lobe', 'two_lobe'):
    for i, vector in enumerate(vectors(family+'_regression_vectors')):
        setattr(AllVectors, f'test_{family}_{i:03}', vector_test(vector))


if __name__ == '__main__':
    unittest.main()

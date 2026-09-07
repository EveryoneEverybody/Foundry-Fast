"""Source routing and option pruning without Blender or proprietary source tags."""
import ast
import importlib
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from test_h3_scenario_scene import PKG, ROOT
from h3_scenario_content_fixture import content_inventory

m = importlib.import_module(PKG + '.scenario_options')
c = importlib.import_module(PKG + '.scenario_content')
s = importlib.import_module(PKG + '.scenario_scene')


class OptionsTests(unittest.TestCase):
    def test_roots_classify_before_any_decoder(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            reach = root / 'Reach/tags'; h3 = root / 'H3EK/tags'
            reach.mkdir(parents=True); h3.mkdir(parents=True)
            for folder, kind in ((reach, 'reach'), (h3, 'halo3')):
                path = folder / 'test.scenario'; path.touch()
                self.assertEqual(m.classify_source(path, reach), (kind, folder.resolve()))
            self.assertEqual(m.classify_source(h3/'test.scenario', reach, h3.parent)[0], 'halo3')
            unknown = root / 'test.scenario'; unknown.touch()
            with self.assertRaisesRegex(ValueError, 'Unknown'): m.classify_source(unknown, reach)
            with self.assertRaisesRegex(ValueError, 'Ambiguous'): m.classify_source(reach/'test.scenario', reach, reach)

    def test_same_properties_map_to_source_adapter(self):
        op = SimpleNamespace(tag_bsp_import_geometry=False, tag_scenario_import_objects=True,
            tag_sky='h3:2', build_blender_materials=True, tag_bsp_render_only=True)
        options = m.ScenarioOptions.from_operator(op)
        self.assertFalse(options.geometry); self.assertTrue(options.objects)
        self.assertTrue(options.materials); self.assertEqual(options.sky, 'h3:2')
        self.assertFalse(options.hints)
        for name in ('ai', 'firing_positions', 'giant_hints', 'script_points', 'reference_debug', 'sound', 'light_references', 'detailed_points'):
            self.assertFalse(getattr(options, name))

    def test_disabled_categories_prune_planning(self):
        options = m.ScenarioOptions()
        plan = c.plan(content_inventory(), options=options)
        self.assertFalse(plan['placements']); self.assertFalse(plan['groups']); self.assertFalse(plan['overlays'])
        hints = s.hint_plan(content_inventory(), options=options)
        self.assertTrue(all(not rows for rows in hints.values()))

    def test_objects_do_not_enable_ai_sound_or_light_references(self):
        options = m.ScenarioOptions(objects=True)
        plan = c.plan(content_inventory(), options=options)
        self.assertEqual(len(plan['placements']), 6)
        self.assertTrue(all(g['key'].startswith('folder:') for g in plan['groups']))
        self.assertFalse(plan['overlays'])
        self.assertFalse(options.placement_enabled('sound scenery'))
        self.assertFalse(options.placement_enabled('light volumes'))

    def test_firing_toggle_does_not_enable_other_hints(self):
        plan = s.hint_plan(content_inventory(), options=m.ScenarioOptions(firing_positions=True))
        self.assertEqual(len(plan['firing_positions']), 1)
        self.assertFalse(plan['script_points']); self.assertFalse(plan['sectors']); self.assertFalse(plan['rails'])

    def test_normal_operator_preflights_before_managed_blam(self):
        tree = ast.parse((ROOT/'blender/addons/io_scene_foundry/tools/importer.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'NWO_Import')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'execute')
        calls = [n for n in ast.walk(method) if isinstance(n, ast.Call)]
        route = next(n for n in calls if isinstance(n.func, ast.Attribute) and n.func.attr == 'route')
        mb = next(n for n in calls if isinstance(n.func, ast.Name) and n.func.id == 'start_mb_for_import')
        self.assertLess(route.lineno, mb.lineno)
        # Templates are source-independent, and must never turn on extra diagnostics.
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and 'template' in node.name:
                self.assertFalse(any(isinstance(n, ast.Attribute) and n.attr in m.INSPECTION_PROPERTIES for n in ast.walk(node)))

    def test_reach_backend_and_templates_unchanged(self):
        # Normalized AST from the verified fea63b47 prototype, before this adapter.
        expected = {
            'apply_import_template': '629cb00b3371789b1b1000d30c947d911f4fc5b3fe98a7790926256d657b9b77',
            'set_default_import_template': '0af0e87cdf3d8a9b3e3e33c976ca9e521ff36b4568878e7ad5f480024c79ddfa',
            'import_scenarios': '96f36f5e925538c1152235f7931bf284165f761ac2ba49db084d87d08a76d775',
            'import_bsp': 'b28da8eec63e954e67706c229aa5067c76938dd0dcd0b804b797510a38e7ce44',
        }
        tree = ast.parse((ROOT/'blender/addons/io_scene_foundry/tools/importer.py').read_text())
        actual = {node.name: hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
                  for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in expected}
        self.assertEqual(actual, expected)


if __name__ == '__main__': unittest.main()

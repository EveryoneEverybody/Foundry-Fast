import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment.diagnostic_capture import capture_compare_restore
from port_environment.paths import OutputPaths, digest


class DiagnosticRestorationTests(unittest.TestCase):
    def test_user_shader_is_preserved_and_concurrent_edit_rejects_restoration(self):
        for concurrent_edit in (False, True):
            with self.subTest(concurrent_edit=concurrent_edit), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                for kit in ('h3', 'reach'):
                    for kind in ('tags', 'data'): (root/kit/kind).mkdir(parents=True)
                paths = OutputPaths(root/'h3', root/'reach', 'levels/h3_port/synthetic', allow_nested=True)
                relative = paths.namespace+'/synthetic.scenario_structure_lighting_info'
                lighting = 'tags/'+relative
                bitmap = 'tags/'+paths.namespace+'/synthetic_lightmap.bitmap'
                shader = 'tags/'+paths.namespace+'/fixture.shader'
                run = root/'run'
                for key, content in ((lighting,b'baseline'), (bitmap,b'pixels'), (shader,b'user shader')):
                    target = paths.reach/key; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
                    backup = run/'before'/key; backup.parent.mkdir(parents=True, exist_ok=True); backup.write_bytes(content)
                before = paths.snapshot()
                (paths.reach/lighting).write_bytes(b'power25')
                helper = root/'reader.exe'; helper.write_bytes(b'pinned helper')
                config = dict(pixel_comparison_helper=str(helper), pixel_comparison_helper_sha256=digest(helper))
                if concurrent_edit:
                    (paths.reach/shader).write_bytes(b'new user edit')
                    with self.assertRaisesRegex(ValueError, 'geometry'):
                        capture_compare_restore(paths, run, before, relative, config, root/'no-blob')
                    self.assertEqual((paths.reach/shader).read_bytes(), b'new user edit')
                    self.assertEqual((paths.reach/lighting).read_bytes(), b'power25')
                    self.assertEqual((run/'after'/shader).read_bytes(), b'new user edit')
                else:
                    result = SimpleNamespace(returncode=0, stdout='{"changed_pixel_bytes":0}')
                    with patch('port_environment.diagnostic_capture.subprocess.run', return_value=result):
                        report = capture_compare_restore(paths, run, before, relative, config, root/'no-blob')
                    self.assertTrue(report['baseline_restored_exactly'])
                    self.assertEqual(paths.snapshot(), before)
                    self.assertEqual((paths.reach/shader).read_bytes(), b'user shader')

    def test_payload_comparison_failure_still_restores_exact_baseline(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for kit in ('h3', 'reach'):
                for kind in ('tags', 'data'): (root/kit/kind).mkdir(parents=True)
            paths = OutputPaths(root/'h3', root/'reach', 'levels/h3_port/synthetic', allow_nested=True)
            relative = paths.namespace+'/synthetic.scenario_structure_lighting_info'
            keys = ['tags/'+relative, 'tags/'+paths.namespace+'/synthetic_lightmap.bitmap']
            run = root/'run'
            for key in keys:
                target = paths.reach/key; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(b'baseline')
                backup = run/'before'/key; backup.parent.mkdir(parents=True, exist_ok=True); backup.write_bytes(b'baseline')
            before = paths.snapshot()
            (paths.reach/keys[0]).write_bytes(b'power25')
            helper = root/'reader.exe'; helper.write_bytes(b'pinned helper')
            config = dict(pixel_comparison_helper=str(helper), pixel_comparison_helper_sha256=digest(helper))
            with patch('port_environment.diagnostic_capture.subprocess.run', return_value=SimpleNamespace(returncode=1, stderr='decode failed')):
                with self.assertRaisesRegex(RuntimeError, 'decode failed'):
                    capture_compare_restore(paths, run, before, relative, config, root/'no-blob')
            self.assertEqual(paths.snapshot(), before)
            report = json.loads((run/'pixel-payload-comparison.json').read_text())
            self.assertEqual(report['status'], 'COMPARISON_FAILED')
            self.assertTrue(report['baseline_restored_exactly'])


if __name__ == '__main__':
    unittest.main()

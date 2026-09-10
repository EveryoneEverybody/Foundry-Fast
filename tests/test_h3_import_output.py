"""H3 viewer launch and bounded log relay without Blender or helper executables."""
import ast
from contextlib import redirect_stdout
import importlib.util
import io
import re
import time
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry/h3_import'
spec = importlib.util.spec_from_file_location('h3_output_test', ROOT / 'import_output.py')
output = importlib.util.module_from_spec(spec)
spec.loader.exec_module(output)


class OutputTests(unittest.TestCase):
    def viewer_status(self):
        tree = ast.parse((ROOT.parent / 'foundry_output_viewer.pyw').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ExportStatus')
        namespace = {'re': re, 'time': time, 'ANSI_ESCAPE': re.compile(r'\x1b\[[0-9;]*m')}
        for name in ('TRACEBACK_START_LINE', 'FATAL_PYTHON_LINE', 'FAILURE_LINE', 'CANCELLED_LINE',
                     'EXPORT_BANNER_LINE', 'SECTION_LINE', 'EXPORT_COMPLETE_LINE'):
            node = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
            exec(compile(ast.Module(body=[node], type_ignores=[]), '<viewer>', 'exec'), namespace)
        exec(compile(ast.Module(body=[cls], type_ignores=[]), '<viewer>', 'exec'), namespace)
        return namespace['ExportStatus']()

    def test_parent_stays_active_through_helpers_validation_and_retention(self):
        viewer = self.viewer_status()
        now = [0.]
        lines = []
        def emit(line, **kwargs):
            lines.append(line)
            viewer.feed(line + '\n')
        reporter = output.ImportProgress('asset', clock=lambda: now[0], emit=emit)
        reporter.update('Reading source')
        viewer.feed('H3 shader extraction complete: 0 shaders, 0 bitmap bindings\n')
        viewer.feed('BSP 0 extraction failed: missing dependency\n')
        self.assertEqual(viewer.state, 'active')
        now[0] = 1.
        reporter.update('Validating inventory: 100/200 fields')
        now[0] = 2.
        reporter.update('Retaining source inventory: 4/8 chunks')
        self.assertIn('4/8 chunks', viewer.status)
        reporter.finish('completed')
        self.assertEqual(viewer.state, 'success')
        reporter.update('late message', force=True)
        reporter.finish('failed')
        self.assertEqual(len(lines), 4)

    def test_throttle_header_and_terminal_states(self):
        for terminal in ('cancelled', 'failed'):
            viewer = self.viewer_status()
            area = SimpleNamespace(header_text_set=Mock())
            lines = []
            reporter = output.ImportProgress('animation', area, clock=lambda: 0., emit=lambda line, **kw: lines.append(line))
            for i in range(50):
                reporter.update(f'Construction {i}/50')
            self.assertEqual(len(lines), 1)
            self.assertEqual(area.header_text_set.call_count, 50)
            reporter.finish(terminal)
            viewer.feed('\n'.join(lines) + '\n')
            self.assertTrue(viewer.finished)
            self.assertEqual(viewer.state, 'failed')

    def test_open_existing_foundry_viewer(self):
        utils = SimpleNamespace(show_output=Mock())
        output.open_output(utils, SimpleNamespace(app=SimpleNamespace(background=False)))
        utils.show_output.assert_called_once_with()

    def test_headless_tests_do_not_launch_viewer(self):
        utils = SimpleNamespace(show_output=Mock())
        output.open_output(utils, SimpleNamespace(app=SimpleNamespace(background=True)))
        utils.show_output.assert_not_called()

    def test_viewer_failure_is_reported_not_fatal(self):
        utils = SimpleNamespace(show_output=Mock(side_effect=OSError('missing viewer')))
        with redirect_stdout(io.StringIO()) as text:
            output.open_output(utils, SimpleNamespace())
        self.assertIn('missing viewer', text.getvalue())

    def test_both_import_commands_open_output_before_launching_helper(self):
        for filename, clsname in [('__init__.py', 'NWO_OT_ImportHalo3Object'),
                                  ('animation_ops.py', 'NWO_OT_ImportH3Animations')]:
            tree = ast.parse((ROOT / filename).read_text())
            cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == clsname)
            execute = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'execute')
            calls = [n for n in ast.walk(execute) if isinstance(n, ast.Call)]
            opens = [n for n in calls if isinstance(n.func, ast.Name) and n.func.id == 'open_output']
            launches = [n for n in calls if isinstance(n.func, ast.Attribute) and n.func.attr == 'Popen']
            self.assertEqual(len(opens), 1)
            self.assertLess(opens[0].lineno, min(n.lineno for n in launches))
            # Cancellation from the existing viewer's print proxy rolls back the import.
            self.assertTrue(any(isinstance(n, ast.ExceptHandler) and isinstance(n.type, ast.Name)
                                and n.type.id == 'KeyboardInterrupt' for n in ast.walk(execute)))

    def test_log_is_relayed_once_with_split_utf8(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'helper.log'
            encoded = 'section café\nprogress 100000\n'.encode()
            path.write_bytes(encoded[:12])
            tail = output.HelperLogTail()
            tail.follow(path)
            with redirect_stdout(io.StringIO()) as text:
                tail.poll()
                with path.open('ab') as f:
                    f.write(encoded[12:])
                tail.poll()
                tail.poll(final=True)
                tail.poll()
            self.assertEqual(text.getvalue(), encoded.decode())
            self.assertEqual(tail.tail, encoded.decode())

    def test_each_tick_reads_at_most_64k_and_error_tail_is_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'helper.log'
            path.write_bytes(b'x' * 150_000)
            tail = output.HelperLogTail()
            tail.follow(path)
            with redirect_stdout(io.StringIO()) as text:
                tail.poll()
                self.assertEqual(tail.offset, 65536)
                tail.poll(final=True)
            self.assertEqual(len(text.getvalue()), 150_000)
            self.assertEqual(len(tail.tail), 2000)

    def test_new_helper_resets_tail_and_offset(self):
        for ending in (b'\n', b'\r\n'):
            with self.subTest(ending=ending), tempfile.TemporaryDirectory() as d:
                path = Path(d) / 'helper.log'
                first = b'object output' + ending
                second = b'shader output' + ending
                path.write_bytes(first)
                tail = output.HelperLogTail()
                with redirect_stdout(io.StringIO()) as text:
                    tail.follow(path)
                    tail.poll(final=True)
                    path.write_bytes(second)
                    tail.follow(path)
                    tail.poll(final=True)
                self.assertEqual(tail.tail, second.decode())
                self.assertEqual(text.getvalue(), (first + second).decode())
                self.assertEqual(tail.offset, len(second))


if __name__ == '__main__':
    unittest.main()

"""Cold numerical imports must work without granting access to host modules."""
import ctypes
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry'
sys.path.insert(0, str(ROOT))
from bitmap_workers.codec import load_codec


class CodecRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.codec, self.fingerprint = load_codec()
        self.namespace = self.codec._decode_bitmap_rgba.__func__.__globals__

    def test_native_import_uses_codec_builtins(self):
        # PyImport_Import resolves the import hook in the calling globals.
        native_import = ctypes.pythonapi.PyImport_Import
        native_import.argtypes = [ctypes.py_object]
        native_import.restype = ctypes.py_object
        namespace = dict(self.namespace, native_import=native_import)
        exec("module = native_import('numpy')", namespace)
        self.assertEqual(namespace['module'].__name__, 'numpy')

    def test_native_host_import_is_blocked(self):
        native_import = ctypes.pythonapi.PyImport_Import
        native_import.argtypes = [ctypes.py_object]
        native_import.restype = ctypes.py_object
        namespace = dict(self.namespace, native_import=native_import)
        for name in ('bpy', 'clr', 'pythonnet', 'ManagedBlam'):
            with self.subTest(name=name), self.assertRaisesRegex(ImportError, 'not allowed'):
                exec(f"native_import({name!r})", namespace)
            self.assertNotIn(name, sys.modules)

    def test_runtime_import_is_numpy_only(self):
        hook = self.namespace['__builtins__']['__import__']
        self.assertEqual(hook('numpy').__name__, 'numpy')
        module = hook('numpy.linalg', fromlist=('norm',))
        self.assertTrue(callable(module.norm))
        for name in ('bpy.types', 'bmesh', 'clr', 'pythonnet', 'System',
                     'numpy_host', 'os', 'subprocess', 'io_scene_foundry'):
            with self.subTest(name=name), self.assertRaisesRegex(ImportError, 'not allowed'):
                hook(name)

    def test_relative_runtime_import_is_blocked(self):
        hook = self.namespace['__builtins__']['__import__']
        with self.assertRaisesRegex(ImportError, 'not allowed'):
            hook('numpy', level=1)

    def test_source_cannot_call_runtime_hook(self):
        source = (ROOT / 'managed_blam/bitmap.py').read_text()
        source = source.replace('return rgba.tobytes()', "return __import__('numpy')", 1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bitmap.py'
            path.write_text(source)
            with self.assertRaisesRegex(ValueError, 'Host dependency'):
                load_codec(path)

    def test_constants_cannot_call_runtime_hook(self):
        source = (ROOT / 'managed_blam/bitmap.py').read_text()
        source += "\nBITMAP_FORMAT_TEST = __import__('bpy')\n"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bitmap.py'
            path.write_text(source)
            with self.assertRaisesRegex(ValueError, 'Host dependency'):
                load_codec(path)

    def test_cold_numerical_job_orders(self):
        # Each interpreter starts cold. A warmed parent must not hide a lazy import.
        script = r'''
import hashlib, json, sys
sys.path.insert(0, sys.argv[1])
from bitmap_workers.codec import load_codec
codec, fingerprint = load_codec()
namespace = codec._decode_bitmap_rgba.__func__.__globals__
hook = namespace['__builtins__']['__import__']
imports = []
def record(name, globals=None, locals=None, fromlist=(), level=0):
    imports.append((name, sys._getframe(1).f_code.co_name))
    return hook(name, globals, locals, fromlist, level)
namespace['__builtins__']['__import__'] = record
block = bytes((231, 47, 11, 89, 123, 4, 200, 91, 0, 248, 224, 7, 1, 35, 69, 103))
results = {}
for name in sys.argv[2].split(','):
    if name == 'normal':
        result = codec._decode_bitmap_rgba(64, 64, 38, block * 256)
    elif name == 'color':
        rgba = codec._decode_bitmap_rgba(64, 64, 16, block * 256)
        result = codec._convert_xrgb_rgba_to_srgb(rgba, 1.95)
    else:
        rgba = (bytes(range(256)) * 384)
        result = codec._cubemap_vertical_rgba_to_equirectangular(rgba, 64)
    results[name] = hashlib.sha256(result).hexdigest()
assert not any(name in sys.modules for name in ('bpy', 'bmesh', 'clr', 'pythonnet', 'ManagedBlam'))
print(json.dumps({'results': results, 'imports': imports}))
'''
        expected = None
        for order in ('normal,color,cube', 'cube,normal,color', 'color,cube,normal'):
            with self.subTest(order=order):
                run = subprocess.run([sys.executable, '-I', '-c', script, str(ROOT), order],
                                     capture_output=True, text=True, timeout=30, check=True)
                output = json.loads(run.stdout)
                print(f"Cold bitmap order {order}: runtime imports={output['imports']}")
                if expected is None:
                    expected = output['results']
                self.assertEqual(output['results'], expected)


if __name__ == '__main__':
    unittest.main()

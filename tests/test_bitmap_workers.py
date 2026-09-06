"""Detached decoder equivalence, subprocess isolation and bounded job lifecycle."""
import ast
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry'
sys.path.insert(0, str(ROOT))
from bitmap_workers.codec import METHODS, load_codec
from bitmap_workers.pool import Pool, WorkerFailure
from bitmap_workers.protocol import atomic_json, digest, publish_missing, reservation, validate_recipe

CODEC, FINGERPRINT = load_codec()


def recipe(width=8, height=8, fmt=16, cube=False, convert=False, gamma=1.95):
    return dict(width=width, height=height, format=fmt, cubemap=cube, convert=convert, gamma=gamma)


def payload(spec):
    width = spec['width']; height = spec['height'] * (6 if spec['cubemap'] else 1)
    constants = CODEC._decode_bitmap_rgba.__func__.__globals__
    bpp = constants['UNCOMPRESSED_BITMAP_BYTES_PER_PIXEL'].get(spec['format'])
    if bpp:
        if spec['format'] in {20, 24, 25, 26, 27}:
            return bytes(width * height * bpp)
        return (bytes(range(256)) * (width * height * bpp // 256 + 1))[:width * height * bpp]
    block_size = 8 if spec['format'] in {14, 35, 36, 37, 39, 40, 41, 42, 43, 45, 46, 47} else 16
    block = bytes((231, 47, 11, 89, 123, 4, 200, 91, 0, 248, 224, 7, 1, 35, 69, 103))[:block_size]
    return block * (((width + 3)//4) * ((height + 3)//4))


def serial_outputs(folder, spec, pixels):
    width, height = spec['width'], spec['height']
    rgba = CODEC._decode_bitmap_rgba(width, height * (6 if spec['cubemap'] else 1), spec['format'], pixels)
    if spec['convert']:
        rgba = CODEC._convert_xrgb_rgba_to_srgb(rgba, spec['gamma'])
    raw = Path(folder) / 'serial.tiff'
    CODEC._write_rgba_tiff(str(raw), width, height * (6 if spec['cubemap'] else 1), rgba)
    result = {'raw.tiff': raw.read_bytes()}
    if spec['cubemap']:
        eq = CODEC._cubemap_vertical_rgba_to_equirectangular(rgba, width)
        CODEC._write_rgba_tiff(str(raw), width * 4, height * 2, eq)
        result['equirectangular.tiff'] = raw.read_bytes()
    return result


@contextmanager
def pool(**kwargs):
    value = Pool(sys.executable, **kwargs)
    try:
        yield value
    finally:
        value.close()


class CodecTests(unittest.TestCase):
    def test_no_host_import(self):
        self.assertNotIn('bpy', sys.modules)
        self.assertNotIn('clr', sys.modules)
        self.assertEqual(len(FINGERPRINT), 64)

    def test_methods_are_exact_serial_source(self):
        # No numerical rewrite: compare compiled instructions against the source subset.
        tree = ast.parse((ROOT/'managed_blam/bitmap.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'BitmapTag')
        source_names = {n.name for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in METHODS}
        self.assertEqual(source_names, METHODS)
        for name in METHODS:
            self.assertTrue(callable(getattr(CODEC, name)))

    def test_known_bgra_and_alpha(self):
        self.assertEqual(CODEC._decode_bitmap_rgba(1, 1, 11, bytes([20, 30, 40, 50])), bytes([40, 30, 20, 50]))

    def test_gamma_leaves_alpha(self):
        value = bytes([100, 120, 150, 17, 50, 60, 70, 222])
        result = CODEC._convert_xrgb_rgba_to_srgb(value, 1.95)
        self.assertEqual(result[3::4], value[3::4])
        self.assertNotEqual(result[:3], value[:3])

    def test_loader_rejects_host_dependency(self):
        source = (ROOT/'managed_blam/bitmap.py').read_text()
        source = source.replace('return rgba.tobytes()', 'return bpy.data.images.new("bad")', 1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'bitmap.py'; path.write_text(source)
            with self.assertRaisesRegex(ValueError, 'Host dependency'):
                load_codec(path)

    def test_loader_rejects_import(self):
        source = (ROOT/'managed_blam/bitmap.py').read_text()
        source = source.replace('return rgba.tobytes()', 'import bpy\n        return rgba.tobytes()', 1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'bitmap.py'; path.write_text(source)
            with self.assertRaisesRegex(ValueError, 'Import in'):
                load_codec(path)

    def test_invalid_dimensions_types(self):
        for name, value in [('width', 0), ('width', True), ('height', 16385), ('gamma', float('nan')), ('convert', 1), ('format', -1)]:
            r = recipe(); r[name] = value
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                validate_recipe(r)

    def test_no_extra_recipe_paths(self):
        r = recipe(); r['destination'] = 'D:/tags/bad.shader'
        with self.assertRaises(ValueError): validate_recipe(r)

    def test_cube_geometry_validation(self):
        for r in (recipe(width=7,height=7,cube=True), recipe(width=8,height=4,cube=True)):
            with self.assertRaises(ValueError): validate_recipe(r)

    def test_budget_includes_cube_intermediates(self):
        self.assertGreater(reservation(recipe(cube=True), 1024), reservation(recipe(), 1024))


class WorkerTests(unittest.TestCase):
    def test_all_formats_match_serial(self):
        constants = CODEC._decode_bitmap_rgba.__func__.__globals__
        formats = sorted(set(constants['UNCOMPRESSED_BITMAP_FORMAT_NAMES']) | set(constants['COMPRESSED_BITMAP_FORMAT_NAMES']))
        with pool() as p, tempfile.TemporaryDirectory() as folder:
            for fmt in formats:
                spec = recipe(fmt=fmt)
                data = payload(spec)
                with self.subTest(fmt=fmt):
                    p.submit(fmt, spec, data)
                    files = p.take(fmt)
                    expected = serial_outputs(folder, spec, data)
                    self.assertEqual({n: f.read_bytes() for n,f in files.items()}, expected)
                    p.release(fmt)
            self.assertGreater(len(formats), 30)
            self.assertEqual(p.bytes_reserved, 0)

    def test_parallel_normal_color_and_cubemap(self):
        specs = [recipe(width=64,height=64,fmt=38), recipe(width=64,height=64,fmt=16,convert=True),
                 recipe(width=64,height=64,fmt=11,cube=True), recipe(width=64,height=64,fmt=14,cube=True,convert=True)]
        with pool(workers=2) as p, tempfile.TemporaryDirectory() as folder:
            for index,r in enumerate(specs): p.submit(index,r,payload(r))
            pids=set()
            for index,r in enumerate(specs):
                files=p.take(index); pids.add(p.jobs[index]['result']['pid'])
                self.assertEqual({n:f.read_bytes() for n,f in files.items()},serial_outputs(folder,r,payload(r)))
                p.release(index)
            self.assertEqual(len(pids),2)
            self.assertEqual(p.stats['peak_running_jobs'],2)

    def test_owned_bytes_and_inflight_dedup(self):
        r=recipe(); data=bytearray(payload(r)); expected=bytes(data)
        with pool() as p, tempfile.TemporaryDirectory() as folder:
            first=p.submit('shared',r,data)
            data[:]=bytes(len(data))
            self.assertIs(first,p.submit('shared',r,data))
            self.assertEqual(p.take('shared')['raw.tiff'].read_bytes(),serial_outputs(folder,r,expected)['raw.tiff'])
            self.assertEqual(p.stats['submitted'],1)
            self.assertEqual(p.stats['deduplicated'],1)

    def test_distinct_interpretations_and_sources(self):
        with pool() as p:
            for index, r in enumerate((recipe(convert=False),recipe(convert=True))):
                p.submit(('project',index),r,payload(r))
            a=p.take(('project',0))['raw.tiff'].read_bytes()
            b=p.take(('project',1))['raw.tiff'].read_bytes()
            self.assertNotEqual(a,b)
            self.assertEqual(p.stats['submitted'],2)

    def test_bounded_pending_jobs(self):
        with pool(workers=1) as p:
            r=recipe(); data=payload(r)
            self.assertIsNotNone(p.submit('a',r,data))
            self.assertIsNotNone(p.submit('b',r,data))
            self.assertIsNone(p.submit('c',r,data))
            p.take('a');p.release('a')
            self.assertIsNotNone(p.submit('c',r,data))

    def test_byte_budget(self):
        r=recipe(); data=payload(r); cost=reservation(r,len(data))
        with pool(budget=cost) as p:
            self.assertIsNotNone(p.submit('a',r,data))
            self.assertIsNone(p.submit('b',r,data))
            self.assertLessEqual(p.stats['peak_reserved_bytes'],cost)

    def test_invalid_payload_returns_failure(self):
        with pool() as p:
            p.submit('bad',recipe(),b'bad')
            with self.assertRaisesRegex(WorkerFailure,'decoder rejected'):p.take('bad')

    def test_bad_interpreter_leaves_no_job(self):
        p=Pool('not-a-python-executable')
        try:
            with self.assertRaises(OSError):p.submit('bad',recipe(),payload(recipe()))
            self.assertFalse(p.jobs);self.assertEqual(p.bytes_reserved,0)
        finally:p.close()

    def test_worker_crash_detected(self):
        with pool() as p:
            p.submit('bad',recipe(width=512,height=512),payload(recipe(width=512,height=512)))
            p.slots[0]['process'].kill();p.slots[0]['process'].wait()
            with self.assertRaises(WorkerFailure):p.take('bad')

    def test_timeout(self):
        with pool(timeout=0) as p:
            p.submit('bad',recipe(),payload(recipe()))
            with self.assertRaises(WorkerFailure):p.take('bad')

    def test_cancel_cleanup(self):
        p=Pool(sys.executable)
        p.submit('cancel',recipe(width=512,height=512),payload(recipe(width=512,height=512)))
        processes=[s['process'] for s in p.slots];folder=p.folder
        def cancel():raise KeyboardInterrupt
        try:
            with self.assertRaises(KeyboardInterrupt):p.take('cancel',check_cancel=cancel)
        finally:p.close()
        self.assertTrue(all(c.poll() is not None for c in processes));self.assertFalse(folder.exists())

    def test_discard_running_job_and_close_twice(self):
        with pool() as p:
            p.submit('unused',recipe(),payload(recipe()))
            p.release('unused')
            deadline=time.monotonic()+20
            while p.jobs and time.monotonic()<deadline:p.poll();time.sleep(.01)
            self.assertFalse(p.jobs);self.assertEqual(p.bytes_reserved,0)
            p.close();p.close()

    def test_corrupt_result_rejected(self):
        with pool() as p:
            p.submit('bad',recipe(),payload(recipe()))
            files=p.take('bad');files['raw.tiff'].write_bytes(b'corrupt')
            with self.assertRaisesRegex(WorkerFailure,'checksum'):p.take('bad')

    def test_publish_does_not_clobber_existing(self):
        with tempfile.TemporaryDirectory() as folder:
            src=Path(folder)/'ready';dst=Path(folder)/'data/out.tiff';src.write_bytes(b'generated')
            self.assertTrue(publish_missing(src,dst));self.assertEqual(dst.read_bytes(),b'generated')
            dst.write_bytes(b'artist file');self.assertFalse(publish_missing(src,dst))
            self.assertEqual(dst.read_bytes(),b'artist file');self.assertFalse(list(dst.parent.glob('.foundry*')))

    def test_pool_does_not_add_python_threads(self):
        import threading
        before={t.ident for t in threading.enumerate()}
        with pool() as p:
            p.submit('a',recipe(),payload(recipe()));p.take('a')
            self.assertEqual(before,{t.ident for t in threading.enumerate()})


if __name__=='__main__':unittest.main()

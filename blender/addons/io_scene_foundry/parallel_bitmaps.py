"""Opt-in read-ahead of missing Reach bitmaps into detached preprocessing workers."""
from collections import defaultdict, deque
from contextlib import contextmanager
from functools import wraps
import json
import ntpath
import os
from pathlib import Path
import sys
import threading
from time import perf_counter

import bpy

from . import foundry_output, preferences, utils
from .bitmap_workers.pool import Pool
from .bitmap_workers.protocol import publish_missing, reservation
from .managed_blam import bitmap as bitmaps
from .managed_blam.shader import ShaderTag
from .tools import importer as backend

PROPERTY = 'parallel_bitmap_workers'
MIN_PIXELS = 65536
_originals = []
_sessions = []


def _owner():
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Bitmap tag access and Blender image creation require the main thread')


def _cancel():
    foundry_output._raise_if_cancel_requested()


def _python():
    version = f'{bpy.app.version[0]}.{bpy.app.version[1]}'
    folder = Path(bpy.app.binary_path).parent / version / 'python' / 'bin'
    candidates = [Path(sys.executable), Path(sys.prefix) / 'bin' / 'python.exe',
                  folder / 'python.exe', folder / f'python{sys.version_info.major}.{sys.version_info.minor}']
    for path in candidates:
        if path.name.lower().startswith('python') and path.is_file():
            return path
    raise RuntimeError('Blender bundled Python executable was not found')


def _path(value):
    return ntpath.normcase(ntpath.normpath(str(value)))


def _stamp(path):
    stat = Path(path).stat()
    return stat.st_size, stat.st_mtime_ns


def _recipe(bitmap, convert_color_space):
    if bitmap.block_bitmaps.Elements.Count != 1:
        return None
    element = bitmap.block_bitmaps.Elements[0]
    get = bitmap._select_int
    kind = get(element, 'CharEnum:type', -1)
    fmt = get(element, 'ShortEnum:format', -1)
    if kind not in {0, 2} or fmt not in bitmaps.SUPPORTED_BITMAP_FORMAT_NAMES:
        return None
    return {'width': get(element, 'ShortInteger:width'),
            'height': get(element, 'ShortInteger:height'), 'format': fmt,
            'cubemap': kind == 2,
            'convert': bool(bitmap._should_convert_xrgb_to_srgb(convert_color_space)),
            'gamma': float(bitmap.get_gamma_value())}


def _identity(bitmap, recipe):
    source = Path(bitmap.tags_dir, bitmap.tag_path.RelativePathWithExtension)
    return (_path(bitmap.tags_dir), _path(bitmap.data_dir), _path(source), _stamp(source),
            json.dumps(recipe, sort_keys=True, allow_nan=False))


def _outputs(bitmap, recipe):
    outputs = {'raw.tiff': Path(bitmap._raw_tiff_save_path(''))}
    if recipe['cubemap']:
        outputs['equirectangular.tiff'] = Path(bitmap._raw_cubemap_equirectangular_save_path(''))
    return outputs


class Session:
    def __init__(self, workers):
        self.workers = workers
        self.pool = None
        self.batch = None
        self.stats = defaultdict(float)
        self.bypass = set()
        self.started = perf_counter()

    def get_pool(self):
        if self.pool is None:
            self.pool = Pool(_python(), self.workers)
        return self.pool

    def report(self):
        print('\n[Foundry perf] Parallel bitmap preparation')
        print(f'  workers requested: {self.workers}')
        print(f'  material scope elapsed: {perf_counter() - self.started:.3f}s')
        for name, value in self.stats.items():
            print(f'  {name:<36} {value:12.3f}')
        if self.pool is not None:
            for name, value in self.pool.stats.items():
                print(f'  {name:<36} {value:12.3f}')
        print('  Worker times are summed job elapsed times, not saved wall time.')
        print('  Coverage: explicit missing static bitmaps in each Reach shader; other requests stay serial.')
        print('  Existing TIFFs and forced extraction are not replaced by read-ahead.')

    @contextmanager
    def shader(self, shader):
        _owner()
        previous = self.batch
        batch = {'pending': deque(), 'jobs': {}, 'seen': set()}
        self.batch = batch
        try:
            # Only explicit references are speculative. Defaults and inherited-only maps stay serial.
            try:
                for element in shader.block_parameters.Elements:
                    field = element.SelectField('bitmap')
                    path = field.Path if field is not None else None
                    if path is not None:
                        source = str(path.Filename)
                        key = _path(source)
                        if key not in batch['seen']:
                            batch['seen'].add(key)
                            batch['pending'].append(source)
            except Exception as error:
                self.stats['shader_scan_errors'] += 1
                foundry_output.print_detail(f'Bitmap read-ahead unavailable for this shader: {error}')
                batch['pending'].clear()
            self.fill()
            yield
        finally:
            if self.pool is not None:
                for key in batch['jobs'].values():
                    if key in self.pool.jobs:
                        self.pool.release(key)
                        self.stats['unused_prefetch_jobs'] += 1
            self.batch = previous

    def fill(self):
        batch = self.batch
        if batch is None:
            return
        while batch['pending']:
            _cancel()
            try:
                if self.pool is not None and not self.pool.room():
                    break
            except Exception as error:
                self.stats['pool_errors'] += 1
                foundry_output.print_detail(f'Bitmap read-ahead stopped: {error}')
                batch['pending'].clear()
                return
            source = batch['pending'][0]
            try:
                if not self.capture(source):
                    break
            except Exception as error:
                self.stats['prefetch_errors'] += 1
                foundry_output.print_detail(f'Bitmap read-ahead skipped {source}: {error}')
                self.bypass.add(_path(source))
            batch['pending'].popleft()

    def capture(self, source):
        """Return False only when the bounded queue needs to drain."""
        _owner()
        key = _path(source)
        if key in self.bypass or not Path(source).is_file():
            return True
        rel = utils.relative_path(source)
        normal = Path(utils.get_data_path(), rel).with_suffix('.tiff')
        eq = normal.with_name(normal.stem + '_equirectangular.tiff')
        if any(p.exists() for p in (normal, normal.with_suffix('.tif'), eq, eq.with_suffix('.tif'))):
            self.stats['existing_file_skips'] += 1
            self.bypass.add(key)
            return True
        begin = perf_counter()
        try:
            with bitmaps.BitmapTag(path=source, tag_must_exist=True) as bitmap:
                recipe = _recipe(bitmap, not bitmap.used_as_normal_map())
                if recipe is None:
                    self.stats['unsupported_skips'] += 1
                    self.bypass.add(key)
                    return True
                pixels = recipe['width'] * recipe['height'] * (6 if recipe['cubemap'] else 1)
                if pixels < MIN_PIXELS:
                    self.stats['small_image_skips'] += 1
                    self.bypass.add(key)
                    return True
                outputs = _outputs(bitmap, recipe)
                target = outputs.get('equirectangular.tiff', outputs['raw.tiff'])
                if target.exists() or target.with_suffix('.tif').exists() or bitmaps._bitmap_sequence_paths(target):
                    self.stats['existing_or_sequence_skips'] += 1
                    self.bypass.add(key)
                    return True
                element = bitmap.block_bitmaps.Elements[0]
                offset = bitmap._select_int(element, 'LongInteger:pixels offset', -1)
                size = bitmap._select_int(element, 'LongInteger:pixels size', -1)
                cost = reservation(recipe, size)
                pool = self.get_pool()
                if cost > pool.budget:
                    self.stats['oversize_skips'] += 1
                    self.bypass.add(key)
                    return True
                if not pool.room(cost):
                    return False
                identity = _identity(bitmap, recipe)
                if identity in pool.jobs:
                    self.batch['jobs'][key] = identity
                    self.stats['inflight_reuse'] += 1
                    return True
                if offset < 0:
                    raise ValueError('Invalid processed pixel offset')
                copy_start = perf_counter()
                processed = bitmap._dotnet_bytes_to_bytes(bitmap.tag.SelectField('Data:processed pixel data').GetData())
                if offset + size > len(processed):
                    raise ValueError('Processed pixel payload is truncated')
                payload = processed[offset:offset + size]
                self.stats['payload_copy_seconds'] += perf_counter() - copy_start
                # Workers own these bytes. No .NET field or tag survives this scope.
                job = pool.submit(identity, recipe, payload)
                if job is None:
                    return False
                self.batch['jobs'][key] = identity
                return True
        finally:
            self.stats['tag_capture_seconds_inclusive'] += perf_counter() - begin

    def prepared(self, bitmap, frame_index, suffix, convert_color_space):
        _owner()
        if self.batch is None or frame_index != 0 or suffix:
            return None
        path = _path(Path(bitmap.tags_dir, bitmap.tag_path.RelativePathWithExtension))
        key = self.batch['jobs'].pop(path, None)
        # Remove already demanded candidates so a later refill cannot redo serial work.
        self.batch['pending'] = deque(p for p in self.batch['pending'] if _path(p) != path)
        if key is None or self.pool is None:
            self.stats['serial_requests'] += 1
            return None
        try:
            recipe = _recipe(bitmap, convert_color_space)
            if recipe is None or _identity(bitmap, recipe) != key:
                self.stats['changed_source_or_interpretation'] += 1
                return None
            ready = self.pool.take(key, check_cancel=_cancel)
            begin = perf_counter()
            outputs = _outputs(bitmap, recipe)
            # Recheck after waiting, before committing files prepared from detached source bytes.
            if _identity(bitmap, recipe) != key:
                self.stats['changed_source_or_interpretation'] += 1
                return None
            for name, target in outputs.items():
                publish_missing(ready[name], target)
            self.stats['publish_seconds'] += perf_counter() - begin
            self.stats['prepared_images_used'] += 1
            return str(outputs.get('equirectangular.tiff', outputs['raw.tiff']))
        except Exception as error:
            self.stats['serial_retries'] += 1
            utils.print_warning(f'Bitmap worker failed for {bitmap.tag_path.RelativePathWithExtension}; retrying serially: {error}')
            return None
        finally:
            self.pool.release(key)

    def close(self):
        if self.pool is not None:
            self.pool.close()


def _patch(owner, name, value):
    _originals.append((owner, name, getattr(owner, name)))
    setattr(owner, name, value)


def prepare():
    preferences.FoundryPreferences.__annotations__[PROPERTY] = bpy.props.EnumProperty(
        name='Parallel Bitmap Workers (Experimental)', default='0',
        description='Prepare missing static Reach textures in external Python processes. '
                    'Tag reads and Blender updates stay on the main thread. Existing images and forced extractions stay serial',
        items=[('0', 'Off', 'Use the existing serial bitmap path'),
               ('2', '2 Workers', 'Use two detached bitmap workers'),
               ('4', '4 Workers', 'Use up to four detached bitmap workers')])


def register():
    if _originals:
        return
    original_box = preferences._settings_box
    def box(layout, title):
        result = original_box(layout, title)
        if title == 'Import & Bitmaps':
            result.prop(utils.get_prefs(), PROPERTY)
        return result
    _patch(preferences, '_settings_box', box)

    original_setup = backend.setup_materials
    @wraps(original_setup)
    def setup(context, importer, starting_materials, imported_objects, build_materials,
              always_extract_bitmaps=False, emissive_meshes=None):
        workers = int(getattr(utils.get_prefs(), PROPERTY, '0'))
        if _sessions or not workers or not build_materials or always_extract_bitmaps or importer.corinth:
            return original_setup(context, importer, starting_materials, imported_objects, build_materials,
                                  always_extract_bitmaps, emissive_meshes)
        _owner()
        session = Session(min(workers, max(1, (os.cpu_count() or 2) - 1)))
        _sessions.append(session)
        try:
            return original_setup(context, importer, starting_materials, imported_objects, build_materials,
                                  always_extract_bitmaps, emissive_meshes)
        finally:
            _sessions.pop()
            session.close()
            session.report()
    _patch(backend, 'setup_materials', setup)

    original_nodes = ShaderTag.to_nodes
    @wraps(original_nodes)
    def nodes(shader, material, always_extract_bitmaps=False, generated_uvs=False):
        if not _sessions:
            return original_nodes(shader, material, always_extract_bitmaps, generated_uvs)
        if shader.corinth or always_extract_bitmaps:
            session = _sessions[-1]
            batch, session.batch = session.batch, None
            try:
                return original_nodes(shader, material, always_extract_bitmaps, generated_uvs)
            finally:
                session.batch = batch
        with _sessions[-1].shader(shader):
            return original_nodes(shader, material, always_extract_bitmaps, generated_uvs)
    _patch(ShaderTag, 'to_nodes', nodes)

    original_save = bitmaps.BitmapTag._save_single_raw_tiff
    @wraps(original_save)
    def save(bitmap, frame_index, suffix, convert_color_space):
        if not _sessions or bitmap.corinth:
            return original_save(bitmap, frame_index, suffix, convert_color_space)
        session = _sessions[-1]
        try:
            result = session.prepared(bitmap, frame_index, suffix, convert_color_space)
            if result is not None:
                return result
            begin = perf_counter()
            try:
                return original_save(bitmap, frame_index, suffix, convert_color_space)
            finally:
                session.stats['serial_decode_seconds'] += perf_counter() - begin
        finally:
            session.fill()
    _patch(bitmaps.BitmapTag, '_save_single_raw_tiff', save)


def unregister():
    for owner, name, original in reversed(_originals):
        setattr(owner, name, original)
    _originals.clear()
    preferences.FoundryPreferences.__annotations__.pop(PROPERTY, None)

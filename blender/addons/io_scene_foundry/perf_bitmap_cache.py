from collections import defaultdict
from copy import copy
from functools import wraps
import ntpath
from time import perf_counter

import bpy

from . import utils
from .managed_blam import bitmap as bitmap_module
from .managed_blam import shader as shader_module
from .tools import importer as importer_module

_original_bitmap_to_image = None
_original_shader_bitmap_to_image = None
_original_setup_materials = None
_original_methods = []
_cache = {}
_seen = set()
_active_depth = 0
_hits = 0
_misses = 0
_uncached = 0
_cubemap_hits = 0
_bitmap_time = 0.0
_timings = defaultdict(float)
_counts = defaultdict(int)


def _reset():
    global _hits, _misses, _uncached, _cubemap_hits, _bitmap_time
    _cache.clear()
    _seen.clear()
    _timings.clear()
    _counts.clear()
    _hits = _misses = _uncached = _cubemap_hits = 0
    _bitmap_time = 0.0


def _cache_key(path):
    normalize = lambda value: ntpath.normcase(ntpath.normpath(str(value)))
    return normalize(utils.get_tags_path()), normalize(utils.get_data_path()), normalize(path)


def _image_is_live(info):
    image = getattr(info, 'image', None)
    try:
        return image is not None and bpy.data.images.get(image.name) == image
    except ReferenceError:
        return False


def _image_signature(info):
    image = info.image
    return image.source, image.colorspace_settings.name, image.alpha_mode


def _cacheable(info):
    if not _image_is_live(info) or getattr(info, 'sequence_length', 1) > 1:
        return False
    if info.image.source != 'FILE':
        return False
    # Cache converted static cubemaps, never raw cube-face plates.
    return not getattr(info, 'cubemap', False) or '_equirectangular' in str(info.image_path).lower()


def _cached_bitmap_to_image(path, always_extract_bitmaps=False):
    global _hits, _misses, _uncached, _cubemap_hits, _bitmap_time
    if _active_depth <= 0:
        return _original_shader_bitmap_to_image(path, always_extract_bitmaps)
    key = _cache_key(path)
    _seen.add(key)
    if always_extract_bitmaps:
        _cache.pop(key, None)
        _uncached += 1
    else:
        cached = _cache.get(key)
        if cached is not None:
            info, signature = cached
            if _cacheable(info) and signature == _image_signature(info):
                _hits += 1
                _cubemap_hits += int(bool(info.cubemap))
                return copy(info)
            _cache.pop(key, None)
        _misses += 1
    started = perf_counter()
    try:
        info = _original_shader_bitmap_to_image(path, always_extract_bitmaps)
    finally:
        _bitmap_time += perf_counter() - started
    if not always_extract_bitmaps and info is not None and _cacheable(info):
        _cache[key] = copy(info), _image_signature(info)
    return info


def _setup_materials_with_bitmap_cache(context, importer, starting_materials, imported_objects,
                                      build_materials, always_extract_bitmaps=False, emissive_meshes=None):
    global _active_depth
    if not build_materials:
        return _original_setup_materials(context, importer, starting_materials, imported_objects,
                                         build_materials, always_extract_bitmaps, emissive_meshes)
    outermost = _active_depth == 0
    if outermost:
        _reset()
    _active_depth += 1
    try:
        return _original_setup_materials(context, importer, starting_materials, imported_objects,
                                         build_materials, always_extract_bitmaps, emissive_meshes)
    finally:
        _active_depth -= 1
        if outermost:
            print(f'[Foundry perf] Bitmap reads: {_hits} cache hits ({_cubemap_hits} static cubemaps), '
                  f'{_misses} cache misses, {_uncached} forced reads, {len(_seen)} distinct request keys, '
                  f'{_bitmap_time:.3f}s reading/loading bitmaps')
            for label, elapsed in _timings.items():
                print(f'  {label:<30} {elapsed:9.3f}s  ({_counts[label]} calls)')
            print('  Bitmap subphase timings are inclusive, not disk-speed measurements.')
            _cache.clear()
            _seen.clear()


def register():
    global _original_bitmap_to_image, _original_shader_bitmap_to_image, _original_setup_materials
    if _original_setup_materials is not None:
        return
    _original_bitmap_to_image = bitmap_module.bitmap_to_image
    _original_shader_bitmap_to_image = shader_module.bitmap_to_image
    _original_setup_materials = importer_module.setup_materials
    bitmap_module.bitmap_to_image = _cached_bitmap_to_image
    shader_module.bitmap_to_image = _cached_bitmap_to_image
    importer_module.setup_materials = _setup_materials_with_bitmap_cache
    for name, label in (('__init__', 'bitmap tag open'), ('save_to_tiff', 'TIFF extraction including decode')):
        owner = bitmap_module.BitmapTag
        original = getattr(owner, name)
        owned = name in owner.__dict__
        @wraps(original)
        def timed(self, *args, _original=original, _label=label, **kwargs):
            if not _active_depth:
                return _original(self, *args, **kwargs)
            started = perf_counter()
            try:
                return _original(self, *args, **kwargs)
            finally:
                _timings[_label] += perf_counter() - started
                _counts[_label] += 1
        _original_methods.append((owner, name, original, owned))
        setattr(owner, name, timed)


def unregister():
    global _original_bitmap_to_image, _original_shader_bitmap_to_image, _original_setup_materials
    if _original_setup_materials is None:
        return
    bitmap_module.bitmap_to_image = _original_bitmap_to_image
    shader_module.bitmap_to_image = _original_shader_bitmap_to_image
    importer_module.setup_materials = _original_setup_materials
    for owner, name, original, owned in reversed(_original_methods):
        if owned:
            setattr(owner, name, original)
        else:
            delattr(owner, name)
    _original_methods.clear()
    _original_bitmap_to_image = _original_shader_bitmap_to_image = _original_setup_materials = None
    _reset()

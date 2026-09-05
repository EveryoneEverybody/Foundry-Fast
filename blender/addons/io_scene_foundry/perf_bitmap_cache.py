from time import perf_counter

import bpy

from .managed_blam import bitmap as bitmap_module
from .managed_blam import shader as shader_module
from .tools import importer as importer_module


_original_bitmap_to_image = None
_original_shader_bitmap_to_image = None
_original_setup_materials = None
_cache = {}
_active_depth = 0
_hits = 0
_misses = 0
_uncached = 0
_bitmap_time = 0.0


def _reset():
    global _hits, _misses, _uncached, _bitmap_time
    _cache.clear()
    _hits = 0
    _misses = 0
    _uncached = 0
    _bitmap_time = 0.0


def _cache_key(path):
    return str(path).replace("/", "\\").lower()


def _image_is_live(info):
    image = getattr(info, "image", None)
    return image is not None and image.name in bpy.data.images


def _cached_bitmap_to_image(path, always_extract_bitmaps=False):
    global _hits, _misses, _uncached, _bitmap_time
    if _active_depth <= 0 or always_extract_bitmaps:
        started = perf_counter()
        try:
            return _original_shader_bitmap_to_image(path, always_extract_bitmaps)
        finally:
            if _active_depth > 0:
                _uncached += 1
                _bitmap_time += perf_counter() - started

    key = _cache_key(path)
    cached = _cache.get(key)
    if cached is not None and _image_is_live(cached):
        _hits += 1
        return cached

    started = perf_counter()
    info = _original_shader_bitmap_to_image(path, always_extract_bitmaps)
    _bitmap_time += perf_counter() - started
    _misses += 1

    if (
        info is not None
        and _image_is_live(info)
        and getattr(info, "sequence_length", 1) <= 1
        and not getattr(info, "cubemap", False)
    ):
        _cache[key] = info

    return info


def _setup_materials_with_bitmap_cache(
    context,
    importer,
    starting_materials,
    imported_objects,
    build_materials,
    always_extract_bitmaps=False,
    emissive_meshes=None,
):
    global _active_depth
    if not build_materials:
        return _original_setup_materials(
            context,
            importer,
            starting_materials,
            imported_objects,
            build_materials,
            always_extract_bitmaps,
            emissive_meshes,
        )

    _reset()
    _active_depth += 1
    try:
        return _original_setup_materials(
            context,
            importer,
            starting_materials,
            imported_objects,
            build_materials,
            always_extract_bitmaps,
            emissive_meshes,
        )
    finally:
        _active_depth -= 1
        print(
            f"[Foundry perf] Bitmap reads: {_hits} cache hits, {_misses} unique/static reads, "
            f"{_uncached} uncached/sequence reads, {_bitmap_time:.3f}s spent reading/loading bitmaps"
        )
        _cache.clear()


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


def unregister():
    global _original_bitmap_to_image, _original_shader_bitmap_to_image, _original_setup_materials
    if _original_setup_materials is None:
        return

    bitmap_module.bitmap_to_image = _original_bitmap_to_image
    shader_module.bitmap_to_image = _original_shader_bitmap_to_image
    importer_module.setup_materials = _original_setup_materials

    _original_bitmap_to_image = None
    _original_shader_bitmap_to_image = None
    _original_setup_materials = None
    _reset()

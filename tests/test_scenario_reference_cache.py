"""Isolated cache identity and bitmap reuse checks."""
import importlib
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry'
NAME = 'scenario_cache_test'
package = types.ModuleType(NAME); package.__path__ = [str(ROOT)]; sys.modules[NAME] = package
bpy = types.ModuleType('bpy'); bpy.data = types.SimpleNamespace(images={}); sys.modules['bpy'] = bpy
for part in ('managed_blam', 'tools'):
    package = types.ModuleType(NAME + '.' + part); package.__path__ = []
    sys.modules[package.__name__] = package
utils = types.ModuleType(NAME + '.utils')
utils.get_tags_path = lambda: 'D:/HREK/tags'
utils.get_data_path = lambda: 'D:/HREK/data'
sys.modules[utils.__name__] = utils
for part in ('managed_blam.bitmap', 'managed_blam.shader', 'tools.importer'):
    module = types.ModuleType(NAME + '.' + part); sys.modules[module.__name__] = module
transform = types.ModuleType(NAME + '.managed_blam.import_transform')
transform.signature = lambda settings: (settings.scale, settings.forward_direction)
sys.modules[transform.__name__] = transform
cache = importlib.import_module(NAME + '.perf_bitmap_cache')
reference = importlib.import_module(NAME + '.scenario_reference')


def image_info(path='objects/a/metal.bitmap', cube=False, sequence=1):
    image = types.SimpleNamespace(name=path, source='SEQUENCE' if sequence > 1 else 'FILE',
                                  colorspace_settings=types.SimpleNamespace(name='sRGB'), alpha_mode='STRAIGHT')
    bpy.data.images[path] = image
    return types.SimpleNamespace(image=image, image_path=path + ('_equirectangular.tiff' if cube else '.tiff'),
                                 cubemap=cube, sequence_length=sequence, curve=0, for_normal=False)


class BitmapCacheTests(unittest.TestCase):
    def setUp(self):
        cache._reset(); cache._active_depth = 1; bpy.data.images.clear()
        self.calls = []
        self.info = image_info()
        def load(path, force=False):
            self.calls.append((path, force))
            return self.info
        cache._original_shader_bitmap_to_image = load
        utils.get_tags_path = lambda: 'D:/HREK/tags'
        utils.get_data_path = lambda: 'D:/HREK/data'

    def tearDown(self):
        cache._active_depth = 0
        cache._reset()

    def test_static_reuse(self):
        cache._cached_bitmap_to_image('a'); cache._cached_bitmap_to_image('a')
        self.assertEqual(len(self.calls), 1)

    def test_converted_cubemap_reuse(self):
        self.info = image_info(cube=True)
        cache._cached_bitmap_to_image('a'); cache._cached_bitmap_to_image('a')
        self.assertEqual(len(self.calls), 1); self.assertEqual(cache._cubemap_hits, 1)

    def test_raw_cube_plate_not_reused(self):
        self.info = image_info(cube=True); self.info.image_path = 'cube_face.tiff'
        cache._cached_bitmap_to_image('a'); cache._cached_bitmap_to_image('a')
        self.assertEqual(len(self.calls), 2)

    def test_sequences_not_reused(self):
        self.info = image_info(sequence=6)
        cache._cached_bitmap_to_image('a'); cache._cached_bitmap_to_image('a')
        self.assertEqual(len(self.calls), 2)

    def test_sequence_source_not_reused_even_with_one_frame(self):
        self.info.image.source = 'SEQUENCE'
        cache._cached_bitmap_to_image('a'); cache._cached_bitmap_to_image('a')
        self.assertEqual(len(self.calls), 2)

    def test_force_bypasses_and_evicts(self):
        for force in (False, True, False): cache._cached_bitmap_to_image('a', force)
        self.assertEqual(len(self.calls), 3); self.assertEqual(cache._uncached, 1)

    def test_no_cross_project_reuse(self):
        cache._cached_bitmap_to_image('a')
        utils.get_tags_path = lambda: 'D:/other/tags'
        cache._cached_bitmap_to_image('a'); self.assertEqual(len(self.calls), 2)

    def test_data_root_is_part_of_key(self):
        cache._cached_bitmap_to_image('a')
        utils.get_data_path = lambda: 'D:/other/data'
        cache._cached_bitmap_to_image('a'); self.assertEqual(len(self.calls), 2)

    def test_path_case_and_slashes(self):
        cache._cached_bitmap_to_image('OBJECTS/A.bitmap'); cache._cached_bitmap_to_image('objects\\a.bitmap')
        self.assertEqual(len(self.calls), 1)

    def test_basename_does_not_merge_sources(self):
        cache._cached_bitmap_to_image('objects/a/metal.bitmap'); cache._cached_bitmap_to_image('objects/b/metal.bitmap')
        self.assertEqual(len(self.calls), 2)

    def test_returned_metadata_is_independent(self):
        cache._cached_bitmap_to_image('a')
        second = cache._cached_bitmap_to_image('a'); second.curve = 7; second.for_normal = True
        third = cache._cached_bitmap_to_image('a')
        self.assertEqual(third.curve, 0); self.assertFalse(third.for_normal)
        self.assertIs(third.image, self.info.image)

    def test_missing_image_is_retried(self):
        cache._cached_bitmap_to_image('a'); bpy.data.images.clear(); cache._cached_bitmap_to_image('a')
        self.assertEqual(len(self.calls), 2)

    def test_changed_interpretation_is_revalidated(self):
        for field in ('colorspace', 'alpha'):
            with self.subTest(field=field):
                cache._reset(); self.calls.clear(); self.info = image_info()
                cache._cached_bitmap_to_image('a')
                if field == 'colorspace': self.info.image.colorspace_settings.name = 'Non-Color'
                else: self.info.image.alpha_mode = 'CHANNEL_PACKED'
                cache._cached_bitmap_to_image('a'); self.assertEqual(len(self.calls), 2)

    def test_none_result_is_not_cached(self):
        self.info = None
        cache._cached_bitmap_to_image('a'); cache._cached_bitmap_to_image('a')
        self.assertEqual(len(self.calls), 2)

    def test_inactive_passthrough(self):
        cache._active_depth = 0
        cache._cached_bitmap_to_image('a'); cache._cached_bitmap_to_image('a')
        self.assertEqual(len(self.calls), 2); self.assertEqual(cache._misses, 0)

    def test_nested_material_pass_reuses_outer_cache(self):
        cache._active_depth = 0
        depth = 0
        def setup(*args):
            nonlocal depth
            cache._cached_bitmap_to_image('a')
            if not depth:
                depth += 1
                cache._setup_materials_with_bitmap_cache(None, None, [], [], True)
            cache._cached_bitmap_to_image('a')
        cache._original_setup_materials = setup
        cache._setup_materials_with_bitmap_cache(None, None, [], [], True)
        self.assertEqual(len(self.calls), 1); self.assertFalse(cache._cache); self.assertEqual(cache._active_depth, 0)

    def test_exception_clears_scope(self):
        cache._active_depth = 0
        def fail(*args):
            cache._cached_bitmap_to_image('a'); raise RuntimeError('fixture')
        cache._original_setup_materials = fail
        with self.assertRaises(RuntimeError): cache._setup_materials_with_bitmap_cache(None, None, [], [], True)
        self.assertEqual(cache._active_depth, 0); self.assertFalse(cache._cache)


class RenderKeyTests(unittest.TestCase):
    def setUp(self):
        self.importer = types.SimpleNamespace(tags_dir='D:/HREK/tags', tag_render=True, tag_markers=True,
            from_vert_normals=False, apply_materials=True, prefix_setting='full', corinth=False,
            scene_nwo=types.SimpleNamespace(scale='blender', forward_direction='x', maintain_marker_axis=False))

    def key(self, permutations=(('body', 'default'),), path='a.render_model'):
        return reference.render_key(self.importer, path, permutations)

    def test_permutation_order_is_stable(self):
        self.assertEqual(self.key((('a','b'),('c','d'))), self.key((('c','d'),('a','b'))))

    def test_damage_permutations_are_separate(self):
        self.assertNotEqual(self.key(), self.key((('body','destroyed'),)))

    def test_all_permutations_not_specific(self):
        self.assertNotEqual(self.key(), self.key(()))

    def test_same_basename_different_source(self):
        self.assertNotEqual(self.key(path='a/model.render_model'), self.key(path='b/model.render_model'))

    def test_build_settings_and_project_change_identity(self):
        for name, value in [('tag_markers',False),('tag_render',False),('from_vert_normals',True),
                            ('apply_materials',False),('prefix_setting','none'),('corinth',True),('tags_dir','other/tags')]:
            with self.subTest(name=name):
                old = getattr(self.importer,name); before=self.key(); setattr(self.importer,name,value)
                self.assertNotEqual(before,self.key()); setattr(self.importer,name,old)

    def test_scale_orientation_and_marker_axes_change_identity(self):
        for name,value in [('scale','max'),('forward_direction','y'),('maintain_marker_axis',True)]:
            with self.subTest(name=name):
                old=getattr(self.importer.scene_nwo,name); before=self.key(); setattr(self.importer.scene_nwo,name,value)
                self.assertNotEqual(before,self.key()); setattr(self.importer.scene_nwo,name,old)


if __name__ == '__main__': unittest.main()

"""Validate pose counts and interpretation without Blender or game tags."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from h3_blend_screen_fixture import payload
from h3_overlay_fixture import payload as time_overlay

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('h3_screen_validation', ROOT / 'blender/addons/io_scene_foundry/h3_import/animations.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


class BlendScreenTests(unittest.TestCase):
    def test_nine_samples_and_reference(self):
        p = payload()
        self.assertIs(a.validate_manifest(p), p)
        self.assertTrue(a.is_blend_screen(p['animations'][0]))
        self.assertEqual(p['animations'][0]['decoded']['file_frame_count'], 10)

    def test_old_schemas_reject_screen_contract(self):
        for version in (1, 2):
            p = payload(); p['version'] = version
            with self.assertRaises(ValueError): a.validate_manifest(p)

    def test_schema_three_keeps_time_overlays(self):
        p = time_overlay(); p['version'] = 3
        self.assertIs(a.validate_manifest(p), p)
        self.assertFalse(a.is_blend_screen(p['animations'][0]))

    def test_duration_is_not_pose_count(self):
        p = payload(); p['animations'][0]['source_frame_count'] = 60
        a.validate_manifest(p)
        self.assertEqual(p['animations'][0]['decoded']['decoded_frame_count'], 9)

    def test_resource_count_must_match_samples(self):
        for count in (0, 8, 10, True, 9.5):
            p = payload(); p['animations'][0]['codec_frame_count'] = count
            with self.subTest(count=count), self.assertRaises(ValueError): a.validate_manifest(p)

    def test_asymmetric_grid_is_not_forced_to_nine(self):
        p = payload(); clip = p['animations'][0]; d = clip['decoded']
        d['blend_screen']['counts'] = {'right': 2, 'left': 1, 'down': 1, 'up': 0}
        clip.update(source_frame_count=8, codec_frame_count=8)
        d.update(decoded_frame_count=8, file_frame_count=9)
        d['blend_screen']['sample_count'] = 8
        a.validate_manifest(p)

    def test_invalid_count_and_angle_fail(self):
        for field, value in [('counts', -1), ('counts', True), ('counts', 32768),
                             ('angles', float('nan')), ('angles', -0.1), ('angles', 0), ('angles', True)]:
            p = payload(); p['animations'][0]['decoded']['blend_screen'][field]['right'] = value
            with self.subTest(field=field,value=value), self.assertRaises(ValueError): a.validate_manifest(p)

    def test_missing_screen_fields_fail(self):
        for field in ('index', 'label', 'layout', 'counts', 'angles', 'sample_count', 'source_fields'):
            p = payload(); del p['animations'][0]['decoded']['blend_screen'][field]
            with self.subTest(field=field), self.assertRaises(ValueError): a.validate_manifest(p)

    def test_index_zero_is_not_missing(self):
        p = payload()
        self.assertTrue(a.is_blend_screen(p['animations'][0]))
        for index in (-1, 1, None, False):
            p = payload(); p['animations'][0]['blend_screen'] = index
            with self.subTest(index=index), self.assertRaises(ValueError): a.validate_manifest(p)

    def test_schema_does_not_assert_direction_mapping(self):
        for field, value in [('angle_units', 'degrees'), ('sample_order', 'yaw_major'),
                             ('sample_coordinates', [[0, 0]]*9), ('sample_count', 8)]:
            p = payload(); p['animations'][0]['decoded']['blend_screen'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): a.validate_manifest(p)

    def test_pose_and_time_layouts_do_not_mix(self):
        for layout in ('reference_then_codec_frames', 'codec_frames_then_held_terminal'):
            p = payload(); p['animations'][0]['decoded']['frame_layout'] = layout
            with self.assertRaises(ValueError): a.validate_manifest(p)

    def test_reach_object_space_and_movement_remain_unsupported(self):
        for field, value in [('object_space_parent_count', 1), ('world_relative', True),
                             ('frame_info_type', 'dx,dy')]:
            p = payload(); p['animations'][0][field] = value
            with self.assertRaises(ValueError): a.validate_manifest(p)

    def test_screen_cannot_be_relabelled_as_base(self):
        p = payload(); clip = p['animations'][0]
        clip.update(animation_type='base')
        clip['decoded'].update(kind='JMM', jma_file='clip.jmm', frame_layout='codec_frames_then_held_terminal')
        with self.assertRaises(ValueError): a.validate_manifest(p)

    def test_preview_contract_remains_explicit(self):
        p = payload(); p['animations'][0]['decoded']['overlay']['preview'] = 'composed_on_fixed_reference'
        with self.assertRaises(ValueError): a.validate_manifest(p)

    def test_screens_and_time_overlays_select_independently(self):
        p = payload(); p['animations'].insert(1, time_overlay()['animations'][0])
        for time, screen in [(False, False), (True, False), (False, True), (True, True)]:
            selected = a.selected_manifest(p, time, screen)
            self.assertEqual(selected['animations'][0]['status'] == 'decoded', screen)
            self.assertEqual(selected['animations'][1]['status'] == 'decoded', time)
        self.assertTrue(all(c['status'] == 'decoded' for c in p['animations'][:2]))

    def test_source_record_survives_validation_and_selection(self):
        p = payload(); before = copy.deepcopy(p)
        a.validate_manifest(p)
        selected = a.selected_manifest(p)
        self.assertEqual(p, before)
        self.assertEqual(selected['animations'][0]['decoded'], p['animations'][0]['decoded'])
        self.assertEqual(json.loads(json.dumps(p)), p)

    def test_grid_size_limit(self):
        p = payload(); p['animations'][0]['decoded']['blend_screen']['counts'] = {side: 32767 for side in ('right','left','down','up')}
        with self.assertRaises(ValueError): a.validate_manifest(p)

    def test_unsupported_raw_screen_is_retained(self):
        p = payload(); clip = p['animations'][0]
        clip.update(status='unsupported', blend_screen=99, blend_screen_source={'raw_hex':'deadbeef'})
        a.validate_manifest(p)
        self.assertEqual(clip['blend_screen_source']['raw_hex'], 'deadbeef')


if __name__ == '__main__': unittest.main()

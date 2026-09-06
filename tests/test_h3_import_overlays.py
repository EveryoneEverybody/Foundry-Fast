import copy
import importlib.util
import json
from pathlib import Path
import unittest
from h3_overlay_fixture import payload

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('h3_overlay_validation', ROOT / 'blender/addons/io_scene_foundry/h3_import/animations.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


class OverlayTests(unittest.TestCase):
    def test_valid_overlay_and_round_trip(self):
        p = payload()
        self.assertIs(a.validate_manifest(p), p)
        self.assertEqual(a.validate_manifest(json.loads(json.dumps(p))), p)
        self.assertEqual(a.KINDS['JMO'], 'none')

    def test_validation_preserves_source(self):
        p = payload(); original = copy.deepcopy(p)
        a.validate_manifest(p); self.assertEqual(p, original)

    def test_legacy_schema_does_not_claim_overlays(self):
        p = payload(); p['version'] = 1
        with self.assertRaises(ValueError): a.validate_manifest(p)

    def test_frame_layouts_cannot_be_swapped(self):
        p = payload(); p['animations'][0]['decoded']['frame_layout'] = 'codec_frames_then_held_terminal'
        with self.assertRaises(ValueError): a.validate_manifest(p)

    def test_no_movement_file(self):
        p = payload(); p['animations'][0]['decoded']['motion_file'] = 'motion.jmo'
        with self.assertRaises(ValueError): a.validate_manifest(p)

    def test_no_movement_samples(self):
        p = payload(); p['animations'][0]['decoded']['movement_samples'] = [{'translation': [1, 0, 0]}]
        with self.assertRaises(ValueError): a.validate_manifest(p)

    def test_special_overlay_metadata_rejected(self):
        for key, value in [('blend_screen', 0), ('object_space_parent_count', 1), ('world_relative', True),
                           ('animation_type', 'replacement'), ('frame_info_type', 'dx,dy')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                p = payload(); p['animations'][0][key] = value; a.validate_manifest(p)

    def test_unknown_composition_rejected(self):
        p = payload(); p['animations'][0]['decoded']['overlay']['composition'] = 'add_everything'
        with self.assertRaises(ValueError): a.validate_manifest(p)

    def test_missing_base_is_not_bind_pose_fallback(self):
        p = payload(); p['animations'].pop()
        with self.assertRaises(ValueError): a.validate_manifest(p)

    def test_inherited_or_self_base_rejected(self):
        for key, value in [('graph_index', 0), ('animation_index', 5), ('frame', 1), ('method', 'bind_pose_fallback')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                p = payload(); p['animations'][0]['decoded']['overlay']['base'][key] = value; a.validate_manifest(p)

    def test_reference_transforms_validated(self):
        for field, value in [('rotation', [0, 0, 0, 0]), ('position', [float('nan'), 0, 0]), ('scale', 0)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                p = payload(); p['animations'][0]['decoded']['overlay']['reference_pose'][0][field] = value
                a.validate_manifest(p)

    def test_pose_count_validated(self):
        p = payload(); p['animations'][0]['decoded']['overlay']['base_pose'].pop()
        with self.assertRaises(ValueError): a.validate_manifest(p)

    def test_flags_keep_component_identity(self):
        for bits in ([True], [1, 0], [False, False, False]):
            with self.subTest(bits=bits), self.assertRaises(ValueError):
                p = payload(); p['animations'][0]['decoded']['overlay']['node_flags']['animated_rotation'] = bits
                a.validate_manifest(p)

    def test_overlapping_flags_rejected(self):
        p = payload(); p['animations'][0]['decoded']['overlay']['node_flags']['static_rotation'][0] = True
        with self.assertRaises(ValueError): a.validate_manifest(p)

    def test_unsupported_source_records_remain_intact(self):
        p = payload(); p['animations'][0].update(status='unsupported', blend_screen=0,
                                               source_fields={'data_hex': '001122'})
        self.assertEqual(a.validate_manifest(p)['animations'][0]['source_fields']['data_hex'], '001122')


if __name__ == '__main__': unittest.main()

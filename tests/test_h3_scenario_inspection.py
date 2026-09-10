"""Scenario source identity, coordinates, references and detached payload validation."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry/h3_import/scenario_inspection.py'
SPEC = importlib.util.spec_from_file_location('scenario_inventory_test', PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
Error = module.InspectionError


def field(address, name, value=None, kind='value', type_name='short block index', **kwargs):
    return dict(address=address, name=name, raw_name=name, ordinal=0, type=type_name,
                kind=kind, **({'value': value} if kind == 'value' else {}), **kwargs)


def inventory():
    reference = dict(group=0x73627370, group_name='sbsp', path='levels/solo/040_voi/040_voi.001',
                     extension='scenario_structure_bsp')
    records = [field('giant sector hints#2', 'giant sector hints', kind='block', count=2, type_name='block'),
               field('giant sector hints#2[0]/point#0', 'point', {'values': [1, 2, 3], 'bits': [0, 0, 0]}, type_name='real point 3d'),
               field('giant sector hints#2[1]/point#0', 'point', {'values': [4, 5, 6], 'bits': [0, 0, 0]}, type_name='real point 3d'),
               field('zone#4', 'zone', -1), field('zone#5', 'zone', 0),
               field('structure bsps#6[0]/reference#0', 'reference', reference, type_name='tag reference')]
    return dict(format=module.FORMAT, version=1, source_tag='levels/solo/040_voi/040_voi.scenario',
                source_group='scnr', coordinate_encoding='source_world_units_unmodified', destination_tags_written=False,
                scope=dict(bsp_dependencies_loaded=False, resource_payloads_decoded=False,
                           scripts_executed=False, lossless_tag_roundtrip=False), records=records,
                references=[dict(address=records[-1]['address'], reference=reference)], diagnostics=[])


class InspectionTests(unittest.TestCase):
    def test_validation_does_not_change_source(self):
        data = inventory(); before = deepcopy(data)
        self.assertIs(module.validate(data), data)
        self.assertEqual(data, before)

    def test_duplicate_names_remain_separate(self):
        rows = module.named_fields(inventory(), 'zone')
        self.assertEqual([r['value'] for r in rows], [-1, 0])

    def test_duplicate_addresses_rejected(self):
        data = inventory(); data['records'].append(deepcopy(data['records'][0]))
        with self.assertRaises(Error): module.validate(data)

    def test_subtree_uses_field_boundaries(self):
        data = inventory()
        data['records'].append(field('giant sector hints#20[0]/point#0', 'point', 9))
        self.assertEqual(len(module.subtree(data, 'giant sector hints#2')), 3)
        self.assertEqual(len(module.subtree(data, 'giant sector hints#2[0]')), 1)

    def test_points_not_rescaled_or_inferred_from_vectors(self):
        data = inventory()
        data['records'].append(field('giant sector hints#2[0]/normal#1', 'normal',
                                     {'values': [0, 0, 1], 'bits': [0, 0, 0]}, type_name='real vector 3d'))
        self.assertEqual([p['position'] for p in module.source_points(data, 'giant sector hints#2')],
                         [(1, 2, 3), (4, 5, 6)])

    def test_nonfinite_bits_retained_but_not_drawn(self):
        data = inventory(); data['records'][1]['value'] = {'values': [None, 2, 3], 'bits': [0x7fc00000, 0, 0]}
        module.validate(data)
        with self.assertRaises(Error): module.source_points(data, 'giant sector hints#2')

    def test_nan_json_rejected(self):
        data = inventory(); data['records'][1]['value'] = float('nan')
        with self.assertRaises(Error): module.validate(data)

    def test_dependency_keeps_literal_dots_and_source_identity(self):
        requests = module.dependency_requests(inventory(), 'scenario_structure_bsp')
        self.assertEqual(requests[0]['source_tag'], 'levels/solo/040_voi/040_voi.001.scenario_structure_bsp')
        self.assertNotIn('destination', requests[0])

    def test_reference_must_match_field(self):
        data = inventory(); data['references'][0] = dict(address='zone#4', reference={})
        with self.assertRaises(Error): module.validate(data)

    def test_scope_cannot_claim_decoded_pathfinding(self):
        data = inventory(); data['scope']['resource_payloads_decoded'] = True
        with self.assertRaises(Error): module.validate(data)

    def test_unknown_source_values_are_retained(self):
        data = inventory(); data['records'].append(field('unknown#91', 'unknown', {'representation': 'decoder_debug', 'value': 'opaque'}))
        data['diagnostics'].append({'address': 'unknown#91', 'code': 'value_retained_as_decoder_debug'})
        before = deepcopy(data); module.validate(data); self.assertEqual(data, before)

    def test_blob_size_and_path_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'blobs').mkdir(); (root/'blobs/000000.bin').write_bytes(b'source')
            data = inventory(); data['records'].append(field('script data#10', 'script data', kind='data', file='blobs/000000.bin', bytes=6))
            manifest = root/'scenario.h3inspect.json'; manifest.write_text(json.dumps(data))
            self.assertEqual(module.load(manifest), data)
            (root/'blobs/000000.bin').write_bytes(b'bad')
            with self.assertRaises(Error): module.load(manifest)
            data['records'][-1]['file'] = '../outside.bin'
            with self.assertRaises(Error): module.validate(data)

    def test_unsafe_source_reference_rejected(self):
        for path in ('../outside', 'C:/outside', '//server/share', 'a/../b', 'a//b'):
            data = inventory(); data['references'][0]['reference']['path'] = path
            with self.subTest(path=path), self.assertRaises(Error): module.validate(data)

    def test_json_duplicate_key_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'test.json'; path.write_text('{"version":1,"version":1}')
            with self.assertRaises(Error): module.load(path)

    def test_boolean_version_is_not_an_integer_version(self):
        data = inventory(); data['version'] = True
        with self.assertRaises(Error): module.validate(data)

    def test_reference_address_must_be_text(self):
        data = inventory(); data['references'][0]['address'] = []
        with self.assertRaises(Error): module.validate(data)


if __name__ == '__main__':
    unittest.main()

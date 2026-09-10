"""Adversarial source ownership graphs and pinned decoder identity checks."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry/h3_import'))
from port_environment import physics_association as association


def field(name, value):
    return dict(name=name, type='value', value=value)


def block(name, rows):
    return dict(name=name, type='block', elements=[dict(source_index=i, fields=r) for i, r in enumerate(rows)])


def struct(name, rows):
    return dict(name=name, type='struct', fields=rows)


def ref(kind, index):
    return struct('shape reference', [field('shape type', dict(name=kind)), field('shape', index)])


def fixture():
    source = [block('nodes', [[field('name', 'node')]]),
        block('regions', [[field('name', 'box'), block('permutations', [
            [field('name', name), block('rigid bodies', [[field('rigid body', i)]])]
            for i, name in enumerate(('base', 'damaged'))])]]),
        block('rigid bodies', [[field('node', 0), field('region', 0), field('permutattion', i), ref(*r)]
                              for i, r in enumerate((('box', 0), ('list', 0)))]),
        block('lists', [[field('child shapes size', 2)]]),
        block('list shapes', [[ref('box', 1)], [ref('box', 2)]]),
        block('boxes', [[struct('base', [field('name', 'shape' + str(i)), field('material', 0)])]
                        for i in range(3)])]
    payload = dict(decoder=association.DECODER, physics=dict(shape_space='node_local',
        nodes=[dict(name='node')], shapes=[dict(kind='box', name='shape' + str(i), node=0, material=0)
                                          for i in range(3)]))
    return source, payload


def native_fixture(source):
    source.append(block('materials', [[field('name', 'concrete')]]))
    native = deepcopy(source)
    for i, shape in enumerate(association.elements(native, 'boxes')):
        association.struct(shape['fields'], 'base')[0]['value'] = 'h3_box_' + str(i)
    return native


class PhysicsAssociation(unittest.TestCase):
    def test_same_node_bodies_are_distinguished_by_indexed_ownership(self):
        source, payload = fixture()
        before = deepcopy((source, payload))
        result = association.bind(source, payload)
        self.assertEqual([r['source_body_index'] for r in result], [0, 1, 1])
        self.assertEqual(result[2]['source_reference_path'], (('list', 0), ('box', 2)))
        self.assertEqual(result[2]['source_body_identity'], ('node', 'box', 'damaged'))
        self.assertEqual((source, payload), before)

    def test_list_cycle_duplicate_owner_and_out_of_range_are_rejected(self):
        for kind, index, error in [('list', 0, 'Cyclic'), ('box', 0, 'multiple body'), ('box', 3, 'outside')]:
            source, payload = fixture()
            association.elements(source, 'list shapes')[0]['fields'] = [ref(kind, index)]
            with self.assertRaisesRegex(ValueError, error):
                association.bind(source, payload)

    def test_list_partition_requires_exact_nonempty_ranges(self):
        for count in (-1, 0, 1, 3):
            source, payload = fixture()
            association.elements(source, 'lists')[0]['fields'][0]['value'] = count
            with self.assertRaisesRegex(ValueError, 'list'):
                association.bind(source, payload)

    def test_decoder_drift_skipped_shape_reordering_and_node_mismatch(self):
        for mutation in ('decoder', 'skip', 'order', 'node', 'material'):
            source, payload = fixture()
            shapes = payload['physics']['shapes']
            if mutation == 'decoder': payload['decoder'] = 'unreviewed'
            if mutation == 'skip': shapes.pop()
            if mutation == 'order': shapes.reverse()
            if mutation == 'node': shapes[0]['node'] = -1
            if mutation == 'material': shapes[0]['material'] = 5
            with self.assertRaises(ValueError): association.bind(source, payload)

    def test_inverse_region_table_is_independent_identity_check(self):
        source, payload = fixture()
        association.elements(source, 'rigid bodies')[1]['fields'][2]['value'] = 0
        with self.assertRaisesRegex(ValueError, 'references disagree'):
            association.bind(source, payload)

    def test_unowned_shape_and_unsupported_leaf_remain_blockers(self):
        source, payload = fixture()
        association.elements(source, 'rigid bodies')[1]['fields'][-1] = ref('box', 1)
        with self.assertRaisesRegex(ValueError, 'no source body owner'): association.bind(source, payload)
        source, payload = fixture()
        association.elements(source, 'list shapes')[0]['fields'] = [ref('pill', 0)]
        with self.assertRaisesRegex(ValueError, 'separate adapter'): association.bind(source, payload)

    def test_mopp_and_multiple_lists_follow_explicit_container_indices(self):
        source, payload = fixture()
        source.append(block('mopps', [[field('list', 0)]]))
        association.elements(source, 'rigid bodies')[1]['fields'][-1] = ref('mopp', 0)
        self.assertEqual(association.bind(source, payload)[2]['source_reference_path'],
                         (('mopp', 0), ('list', 0), ('box', 2)))
        source, payload = fixture()
        association.elements(source, 'lists')[0]['fields'][0]['value'] = 1
        association.elements(source, 'lists').append(dict(source_index=1, fields=[field('child shapes size', 1)]))
        association.elements(source, 'list shapes').append(dict(source_index=2, fields=[ref('box', 2)]))
        association.elements(source, 'lists')[0]['fields'][0]['value'] = 2
        association.elements(source, 'list shapes')[1]['fields'] = [ref('list', 1)]
        self.assertEqual(association.bind(source, payload)[2]['source_reference_path'],
                         (('list', 0), ('list', 1), ('box', 2)))

    def test_native_body_order_can_change_but_ownership_cannot(self):
        source, payload = fixture()
        native = native_fixture(source)
        report = association.compare_native(source, payload, native)
        self.assertEqual((report['body_count'], report['leaf_count']), (2, 3))
        bodies = association.elements(native, 'rigid bodies')
        bodies[0]['fields'], bodies[1]['fields'] = bodies[1]['fields'], bodies[0]['fields']
        region = association.elements(native, 'regions')[0]
        for p in association.elements(region['fields'], 'permutations'):
            link = association.elements(p['fields'], 'rigid bodies')[0]['fields'][0]
            link['value'] = 1 - link['value']
        self.assertEqual(association.compare_native(source, payload, native)['leaf_count'], 3)
        bodies[0]['fields'][-1], bodies[1]['fields'][-1] = bodies[1]['fields'][-1], bodies[0]['fields'][-1]
        with self.assertRaisesRegex(ValueError, 'ownership'): association.compare_native(source, payload, native)

    def test_native_material_or_shape_relabeling_is_rejected(self):
        for mutation in ('material', 'shape'):
            source, payload = fixture()
            native = native_fixture(source)
            if mutation == 'material': association.elements(native, 'materials')[0]['fields'][0]['value'] = 'wood'
            else: association.struct(association.elements(native, 'boxes')[0]['fields'], 'base')[0]['value'] = 'other'
            with self.assertRaises(ValueError): association.compare_native(source, payload, native)


if __name__ == '__main__': unittest.main()

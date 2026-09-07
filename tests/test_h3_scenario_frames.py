from copy import deepcopy
import importlib
import math
import unittest
from test_h3_scenario_scene import PKG
from h3_scenario_content_fixture import content_inventory
from h3_scenario_fixture import Fields
from h3_import_fixture import payload

c = importlib.import_module(PKG + '.scenario_content')
f = importlib.import_module(PKG + '.scenario_frames')
s = importlib.import_module(PKG + '.scenario_scene')


def frame_fixture():
    data = content_inventory()
    fields = Fields(); fields.ordinals[''] = 500
    block = fields.block('', 'reference frames', 1)
    frame = fields.element(block)
    oid = fields.add(frame, 'object id', kind='struct', field_type='struct')
    identifier = {'unique id': 123, 'origin bsp index': -1, 'type': {'value': 6, 'name': 'scenery'}, 'source': {'value': 1, 'name': 'editor'}}
    for key, value in identifier.items(): fields.add(oid, key, value)
    fields.add(frame, 'node index', 0); fields.add(frame, 'projection axis', 2); fields.add(frame, 'flags', {'value': 0})
    data['records'].extend(fields.rows)
    content = c.plan(data)
    row = content['placements'][0]
    row['metadata']['object id'] = identifier
    row.update(position=[10.,20.,30.], source_position=[10.,20.,30.], rotation=[math.pi/2,0.,0.], scale=2.)
    model = payload(); model['render']['nodes'] = [dict(name='root', parent=-1, position=[100.,0.,0.], rotation=[1.,0.,0.,0.])]
    resolver = f.FrameResolver(c.ContentIndex(data, c.CONTENT_ROOTS), content['placements'], {row['source_tag']: model})
    return data, content, resolver, model


class ReferenceFrameTests(unittest.TestCase):
    def test_valid_object_node_transform_and_source_unchanged(self):
        data, content, resolver, _ = frame_fixture(); before = deepcopy((data, content))
        actual = resolver.point([1.,0.,0.], 0)
        for a, b in zip(actual, [10.,24.,30.]): self.assertAlmostEqual(a,b)
        self.assertEqual((data,content),before)
        self.assertEqual(resolver.resolved[0]['node_index'],0)
        self.assertEqual(resolver.point([1,2,3],-1),[1,2,3])

    def test_missing_invalid_and_boolean_frame(self):
        _,_,resolver,_ = frame_fixture()
        for frame in (99, -2, None, True):
            with self.subTest(frame=frame), self.assertRaises(ValueError): resolver.point([0,0,0],frame)

    def test_identifier_is_not_name_index_or_unique_id_alone(self):
        _,content,resolver,_ = frame_fixture()
        content['placements'][0]['metadata']['object id']['origin bsp index']=5
        resolver = f.FrameResolver(resolver.index, content['placements'], resolver.payloads)
        with self.assertRaisesRegex(ValueError,'0 placements'): resolver.point([0,0,0],0)

    def test_nested_placement_and_cycle(self):
        _, content, resolver, _ = frame_fixture()
        child, parent = content['placements'][:2]
        parent.update(source_position=[5.,0.,0.], rotation=[0.,0.,0.], scale=1.)
        child.update(parent_name_index=parent['name_index'], parent_marker='', connection_marker='')
        self.assertAlmostEqual(resolver.point([0,0,0],0)[0],15.)
        resolver.object_cache.clear(); resolver.cache.clear()
        parent['parent_name_index']=child['name_index']
        with self.assertRaisesRegex(ValueError,'Cyclic'): resolver.point([0,0,0],0)

    def test_missing_parent_and_invalid_node_and_pose(self):
        for change, match in [('parent','parent'),('node','node'),('pose','stored pose')]:
            _,content,resolver,model=frame_fixture()
            if change=='parent': content['placements'][0]['parent_name_index']=999
            elif change=='node': model['render']['nodes'][0]['parent']=0
            else: content['placements'][0]['stored_pose']=[{'node_count':1}]
            with self.subTest(change=change), self.assertRaisesRegex(ValueError,match): resolver.point([0,0,0],0)

    def test_shared_resolver_routes_firing_and_script_points(self):
        data,_,resolver,_ = frame_fixture()
        for row in data['records']:
            if row['name']=='reference frame' and row['kind']=='value': row['value']=0
        result=s.hint_plan(data,resolver)
        for key in ('firing_positions','script_points'):
            self.assertTrue(result[key]); row=result[key][0]
            self.assertEqual(row['reference_frames'],[0])
            self.assertEqual(row['points'][0],resolver.point(row['source_points'][0],0))

    def test_node_model_space_not_multiplied_twice(self):
        _,_,resolver,model=frame_fixture()
        model['render']['nodes'].append(dict(name='child',parent=0,position=[300,0,0],rotation=[1,0,0,0]))
        self.assertEqual(f.node_matrix(model,1)[0][3],3.)


if __name__ == '__main__': unittest.main()

import importlib
import unittest
from test_h3_scenario_scene import PKG

r=importlib.import_module(PKG+'.scenario_reporting')
p=importlib.import_module(PKG+'.scenario_poses')


class ReportingTests(unittest.TestCase):
    def test_repeated_capabilities_and_specific_errors_remain_counted(self):
        records=[dict(address=str(i),reason='Experimental reconstruction, not a lossless object-tag conversion.') for i in range(1000)]
        records += [dict(address='one',reason='Reference frame 1 unresolved'),dict(address='two',reason='Missing dependency: two')]
        summary=r.summarize(records)
        self.assertEqual(sum(g['count'] for g in summary),1002)
        self.assertEqual(len(list(r.messages(summary))),6)
        self.assertEqual(len(records),1002)

    def test_nested_exclusive_and_generator_suspension(self):
        now=[0.]; profile=r.Profile(lambda:now[0])
        with profile.span('outer'):
            now[0]+=2
            with profile.span('inner'):now[0]+=3
            now[0]+=1
        self.assertEqual(profile.rows['outer']['inclusive_seconds'],6)
        self.assertEqual(profile.rows['outer']['exclusive_seconds'],3)
        def steps():
            now[0]+=1;yield 'first'
            now[0]+=2;return 7
        gen=profile.steps('steps',steps());next(gen);now[0]+=100
        with self.assertRaises(StopIteration) as done:next(gen)
        self.assertEqual(done.exception.value,7)
        self.assertEqual(profile.rows['steps']['inclusive_seconds'],3)

    def test_packed_pose_never_truncated_or_applied_to_mismatched_hierarchy(self):
        pose=dict(node_count=1,bit_vector=[1],orientations=[0,0,0,32767,123])
        model=dict(render=dict(nodes=[dict(name='root')]))
        result=p.validate_stored_pose([pose],model)
        self.assertIn('5 packed shorts',result['reason'])
        self.assertEqual(pose['orientations'][-1],123)
        model['render']['nodes']=[]
        self.assertIn('node-count mismatch',p.validate_stored_pose([pose],model)['reason'])


if __name__=='__main__':unittest.main()

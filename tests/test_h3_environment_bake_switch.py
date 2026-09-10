from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment.bake_switch import switch
from port_environment.paths import OutputPaths, digest


class ComparisonSwitch(unittest.TestCase):
    def make(self, directory):
        root=Path(directory)
        for kit in ('h3','reach'):
            for kind in ('data','tags'):(root/kit/kind).mkdir(parents=True)
        paths=OutputPaths(root/'h3',root/'reach','levels/h3_port/synthetic',allow_nested=True)
        key='tags/levels/h3_port/synthetic/synthetic.scenario_lightmap'
        target=paths.reach/key;target.parent.mkdir(parents=True);target.write_bytes(b'baseline')
        variants={}
        for name,content in [('baseline',b'baseline'),('scale10',b'diagnostic')]:
            capture=root/name;p=capture/key;p.parent.mkdir(parents=True);p.write_bytes(content)
            variants[name]=dict(capture_root=str(capture),files={key:digest(p)})
        r=dict(h3_root=str(paths.h3),reach_root=str(paths.reach),namespace=paths.namespace,variants=variants,diagnostic_lighting_key='unused')
        return paths,key,r

    def test_roundtrip_restores_exact_hashes_without_rebaking(self):
        with tempfile.TemporaryDirectory() as d:
            p,key,r=self.make(d)
            self.assertEqual(switch(r,'scale10',dry_run=True)['changed_files'],[key])
            self.assertEqual((p.reach/key).read_bytes(),b'baseline')
            switch(r,'scale10');self.assertEqual((p.reach/key).read_bytes(),b'diagnostic')
            switch(r,'baseline');self.assertEqual((p.reach/key).read_bytes(),b'baseline')

    def test_unrecognized_user_edit_prevents_any_writes(self):
        with tempfile.TemporaryDirectory() as d:
            p,key,r=self.make(d);(p.reach/key).write_bytes(b'user edit')
            with self.assertRaisesRegex(ValueError,'unrecognized'):switch(r,'scale10')
            self.assertEqual((p.reach/key).read_bytes(),b'user edit')

    def test_corrupted_capture_prevents_any_writes(self):
        with tempfile.TemporaryDirectory() as d:
            p,key,r=self.make(d);(Path(r['variants']['scale10']['capture_root'])/key).write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError,'absent or changed'):switch(r,'scale10')
            self.assertEqual((p.reach/key).read_bytes(),b'baseline')

    def test_bsp_geometry_is_outside_comparison_scope(self):
        with tempfile.TemporaryDirectory() as d:
            p,key,r=self.make(d)
            bad=key.replace('scenario_lightmap','scenario_structure_bsp')
            for state in r['variants'].values():
                state['files']={bad:state['files'][key]}
            (p.reach/key).rename(p.reach/bad)
            with self.assertRaisesRegex(ValueError,'geometry'):switch(r,'scale10')

    def test_sun_control_exception_is_one_explicit_owned_sky_input(self):
        with tempfile.TemporaryDirectory() as d:
            p,key,r=self.make(d)
            sky='tags/'+p.namespace+'/sky/control.render_model'
            for state in r['variants'].values():
                source=Path(state['capture_root'])/key
                dest=Path(state['capture_root'])/sky; dest.parent.mkdir(parents=True)
                source.rename(dest); state['files']={sky:state['files'][key]}
            target=p.reach/sky; target.parent.mkdir(parents=True); (p.reach/key).rename(target)
            r['diagnostic_lighting_key']=sky
            with self.assertRaisesRegex(ValueError,'geometry'):switch(r,'scale10')
            r.update(sun_control_key=sky,sun_control_kind='ANALYTIC_SUN_INPUT')
            switch(r,'scale10'); switch(r,'baseline')
            self.assertEqual(target.read_bytes(),b'baseline')


if __name__=='__main__':unittest.main()

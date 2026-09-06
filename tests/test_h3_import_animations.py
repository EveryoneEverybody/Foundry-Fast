import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from h3_animation_fixture import payload, scarab_metadata

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('h3_animations', ROOT / 'blender/addons/io_scene_foundry/h3_import/animations.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


class AnimationManifestTests(unittest.TestCase):
    def test_valid(self):
        p = payload()
        self.assertIs(a.validate_manifest(p), p)

    def test_version_two_base(self):
        p = payload()
        p['version'] = 2
        self.assertIs(a.validate_manifest(p), p)

    def test_format(self):
        for key, value in [('format','foreign'), ('version',4), ('game','haloreach'), ('rest_space','world'), ('units','meters'), ('quaternion_order','xyzw')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                p=payload();p[key]=value;a.validate_manifest(p)

    def test_bad_quaternion(self):
        p=payload();p['nodes'][0]['rest']['rotation']=[0,0,0,0]
        with self.assertRaises(ValueError):a.validate_manifest(p)

    def test_nonfinite(self):
        p=payload();p['nodes'][0]['rest']['position'][1]=float('nan')
        with self.assertRaises(ValueError):a.validate_manifest(p)

    def test_wrong_parent(self):
        for v in (-1,1,2,True):
            with self.subTest(parent=v),self.assertRaises(ValueError):
                p=payload();p['nodes'][1]['parent']=v;a.validate_manifest(p)

    def test_duplicate_nodes(self):
        p=payload();p['nodes'][1]['name']='hull'
        with self.assertRaises(ValueError):a.validate_manifest(p)

    def test_duplicate_clips(self):
        p=payload();p['animations'].append(copy.deepcopy(p['animations'][0]))
        with self.assertRaises(ValueError):a.validate_manifest(p)

    def test_frame_counts(self):
        for k,v in [('file_frame_count',2),('decoded_frame_count',99),('fps',24),('frame_layout','leading_rest')]:
            with self.subTest(k=k),self.assertRaises(ValueError):
                p=payload();p['animations'][0]['decoded'][k]=v;a.validate_manifest(p)

    def test_motion_required(self):
        p=payload();p['animations'][0]['decoded']['motion_file']=None
        with self.assertRaises(ValueError):a.validate_manifest(p)

    def test_idle_needs_no_motion_file(self):
        p=payload();c=p['animations'][0];c['frame_info_type']='none';c['decoded'].update(kind='JMM',jma_file='clip.jmm',motion_file=None)
        a.validate_manifest(p)

    def test_unknown_kind_not_treated_as_idle(self):
        p=payload();p['animations'][0]['decoded']['kind']='JMV'
        with self.assertRaises(ValueError):a.validate_manifest(p)

    def test_overlay_not_staged_as_base(self):
        p=payload();p['animations'][0]['animation_type']='overlay'
        with self.assertRaises(ValueError):a.validate_manifest(p)

    def test_unsupported_metadata_retained(self):
        p=payload();c=p['animations'][0];c.update(status='unsupported',animation_type='overlay',source_fields={'function_data_hex':'aabb'})
        self.assertEqual(a.validate_manifest(p)['animations'][0]['source_fields']['function_data_hex'],'aabb')

    def test_paths(self):
        for p in ('../x','/tmp/x','a/../../x','C:/x','a\\x','a//x','a/./x','a:stream',''):
            with self.subTest(path=p),self.assertRaises(ValueError):a.safe_file('.',p)
        self.assertEqual(a.safe_file('.', 'files/x.jma').name,'x.jma')

    def test_symlink_escape(self):
        with tempfile.TemporaryDirectory() as folder,tempfile.TemporaryDirectory() as other:
            link=Path(folder)/'outside'
            try:link.symlink_to(other,target_is_directory=True)
            except OSError:self.skipTest('Symlinks not permitted')
            with self.assertRaises(ValueError):a.safe_file(folder,'outside/x.jma')

    def test_header(self):
        with tempfile.TemporaryDirectory() as f:
            p=Path(f)/'x.jma';p.write_text('16392\n3\n30\n1\nactor\n2\n0\n')
            a.validate_jma_header(p,3,2)
            with self.assertRaises(ValueError):a.validate_jma_header(p,2,2)


class NodeMatchingTests(unittest.TestCase):
    def test_source_names(self):
        mapping,ped=a.node_mapping(payload()['nodes'],{'hull':None,'leg':'hull'})
        self.assertEqual(mapping,{'hull':'hull','leg':'leg'});self.assertIsNone(ped)

    def test_reach_names(self):
        mapping,ped=a.node_mapping(payload()['nodes'],{'b_pedestal':None,'b_hull':'b_pedestal','b_leg':'b_hull','b_leg_atr_u':'b_leg'})
        self.assertEqual(mapping['hull'],'b_hull');self.assertEqual(ped,'b_pedestal')

    def test_ambiguous_names(self):
        with self.assertRaises(ValueError):a.node_mapping(payload()['nodes'],{'hull':None,'b_hull':None,'leg':'hull'})

    def test_control_not_a_match(self):
        with self.assertRaises(ValueError):a.node_mapping(payload()['nodes'],{'CTRL_hull':None,'leg':'CTRL_hull'})

    def test_wrong_hierarchy(self):
        with self.assertRaises(ValueError):a.node_mapping(payload()['nodes'],{'b_hull':None,'b_leg':None})

    def test_real_scarab_node_correspondence(self):
        f=scarab_metadata();nodes=f['target_nodes']
        parents={n['name']:nodes[n['parent']]['name'] if n['parent']!=-1 else None for n in nodes}
        mapping,ped=a.node_mapping(f['source_nodes'],parents)
        self.assertEqual(len(mapping),33);self.assertEqual(len(nodes),47);self.assertEqual(ped,'b_pedestal')
        self.assertEqual(set(parents)-set(mapping.values()), {'b_pedestal','b_aim_yaw','b_aim_pitch'}|{n['name'] for n in nodes if n['name'].endswith('_atr_u')})

    def test_real_scarab_clip_counts(self):
        f=scarab_metadata();clips={c['name']:c for c in f['source_clips']}
        self.assertEqual(len(clips),25)
        self.assertEqual(clips['combat:move_front']['frame count'],'60')
        self.assertEqual(clips['combat:move_front']['frame info type'],'dx,dy')
        self.assertEqual(clips['combat:buckle_wobble']['animation type'],'overlay')

if __name__ == '__main__':unittest.main()

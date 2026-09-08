"""Identity remapping and typed authoring boundaries for non-unit objects."""
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment import object_ir,native_object_tags as tags,native_placements as places


class ObjectContracts(unittest.TestCase):
    def test_ambiguous_dependency_is_rejected(self):
        reference=dict(name='model',value=dict(path='x/a',extension='model'))
        with self.assertRaisesRegex(ValueError,'Ambiguous'):
            object_ir.dependency(dict(fields=[reference,dict(name='nested',fields=[reference])]),'model')

    def test_flags_use_names_instead_of_source_ordinals(self):
        native=SimpleNamespace(Items=[SimpleNamespace(FlagName=n,IsSet=False) for n in ('unused','lock transform to env. object')])
        source=dict(type='long flags',value=dict(value=4,set_bits=[[2,'lock transform to env. object']]))
        tags.write(native,source)
        self.assertFalse(native.Items[0].IsSet)
        self.assertTrue(native.Items[1].IsSet)

    def test_unknown_flag_cannot_be_silently_lost(self):
        with self.assertRaisesRegex(ValueError,'Unmapped'):
            tags.write(SimpleNamespace(Items=[]),dict(type='flags',value=dict(set_bits=[[0,'required behavior']])))

    def test_enum_uses_native_name(self):
        target=SimpleNamespace(Items=[SimpleNamespace(EnumName='cut-out',EnumIndex=4)],Value=-1)
        tags.write(target,dict(type='short enum',value=dict(name='cut_out',value=2)))
        self.assertEqual(target.Value,4)

    def test_unlabeled_xml_flags_are_not_inferred(self):
        with self.assertRaisesRegex(ValueError,'lack named evidence'):
            places.xml_write(None,dict(type='word flags',name='flags',value='8',set_flags=[]))

    def test_fraction_bounds_are_not_executable_text(self):
        with self.assertRaisesRegex(ValueError,'Unsupported'):
            tags.write(SimpleNamespace(),dict(type='real fraction bounds',name='bounds',value='__import__("os")'))

    def test_sparse_palettes_and_parent_closure(self):
        def placement(i,pi,parent=-1,pose=0):
            return dict(source_index=i,source_palette_index=pi,source_problems=[],source_object_name_index=i,
                parent=dict(source_name_index=parent),stored_pose_count=pose)
        inventory=dict(families={f:dict(palette=[],placements=[]) for f in places.SUPPORTED})
        inventory['families']['scenery']=dict(palette=[dict(source_index=i,source_tag=s) for i,s in enumerate(('a','missing','c'))],
            placements=[placement(0,0,pose=1),placement(1,1),placement(2,2,parent=1),placement(3,2,parent=2)])
        original=deepcopy(inventory)
        out=places.plan(inventory,{s:dict(target_tag='native/'+s) for s in ('a','c')},{})['families']['scenery']
        self.assertEqual(inventory,original)
        self.assertEqual(out['palette'][2]['target_index'],1)
        self.assertEqual(out['translated_instance_count'],1)
        self.assertEqual(out['placements'][0]['classification'],'STATICIZED_MVP')
        self.assertEqual(out['placements'][3]['native_status'],'DEFERRED')

    def test_nested_struct_flags_remain_distinct(self):
        rows=[dict(name='device data',type='struct'),dict(name='flags',type='flags',value='1'),
              dict(name='machine data',type='struct'),dict(name='flags',type='flags',value='2')]
        self.assertEqual(places.section(rows,'device data')[0]['value'],'1')
        self.assertEqual(places.section(rows,'machine data')[0]['value'],'2')


if __name__=='__main__':unittest.main()

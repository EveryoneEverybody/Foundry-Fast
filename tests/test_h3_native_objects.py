"""Identity remapping and typed authoring boundaries for non-unit objects."""
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment import object_ir,native_object_tags as tags,native_placements as places


class ObjectContracts(unittest.TestCase):
    def test_missing_bitmap_preserves_decoder_error_before_layout_admission(self):
        from port_environment.model import bitmap_strategy
        error='Missing dependency: objects/pallet_change color.bitmap: The system cannot find the file specified. (os error 2)'
        with self.assertRaises(ValueError) as caught:
            bitmap_strategy(dict(status='error',error=error,index=0))
        self.assertEqual(str(caught.exception),'Source bitmap unavailable: '+error)
        self.assertNotIn('indexed',str(caught.exception))

    def test_structure_origin_reconstruction_preserves_source_and_spawn_policy(self):
        records=[dict(name='placement flags',type='long flags',value='23',set_flags=[
            'not automatically','lock type to env. object','lock transform to env. object','lock name to env. object']),
            dict(name='object id',type='struct'),dict(name='source',type='char enum',value='structure'),
            dict(name='unique id',type='long integer',value='9880800')]
        row=dict(source_records=records,stored_pose_count=0)
        before=deepcopy(row)
        native=places.placement_records(row)
        self.assertEqual(row,before)
        self.assertEqual(places.first(native,'placement flags')['set_flags'],['not automatically'])
        self.assertEqual(places.first(native,'source')['value'],'editor')
        self.assertEqual(places.first(native,'unique id')['value'],'9880800')
        row['source_records'][2]['value']='editor'
        self.assertEqual(places.placement_records(row),row['source_records'])

    def test_structure_origin_reconstruction_rejects_existing_environment_objects(self):
        places.require_empty_environment_objects([dict(environment_objects=0,environment_object_palette=0)])
        for counts in ([],[dict(environment_objects=1,environment_object_palette=0)],
                       [dict(environment_objects=0,environment_object_palette=1)]):
            with self.assertRaisesRegex(ValueError,'empty native BSP'):places.require_empty_environment_objects(counts)

    def test_receipt_reuse_rejects_modified_outputs_and_partial_accounting(self):
        from port_environment.object_receipts import verify_reuse
        plan=dict(plan_sha256='plan',objects=[dict(source_tag='source',target_tag='native',plan_status='READY_FOR_NATIVE')])
        receipt=dict(status='COMPLETE',plan_sha256='plan',generated_files=[dict(path='tags/native',sha256='bytes')],
            worker=dict(objects=[dict(source_tag='source',target_tag='native',status='NATIVE_COMPILED')]))
        self.assertEqual(verify_reuse(receipt,plan,{'tags/native':'bytes'}),1)
        with self.assertRaisesRegex(ValueError,'changed'):verify_reuse(receipt,plan,{'tags/native':'user edit'})
        receipt['worker']['objects']=[]
        with self.assertRaisesRegex(ValueError,'accounting'):verify_reuse(receipt,plan,{'tags/native':'bytes'})

    def test_physics_shape_does_not_guess_between_bodies_on_one_node(self):
        from port_environment import native_physics
        payload=dict(physics=dict(nodes=[dict(name='arm')]))
        with patch.object(native_physics,'source_bodies',return_value={('arm','door','intact'):{}}):
            self.assertEqual(native_physics.shape_region_permutation({},dict(node=0),payload),('door','intact'))
        with patch.object(native_physics,'source_bodies',return_value={('arm','door','intact'):{},('arm','door','damaged'):{}}):
            with self.assertRaisesRegex(ValueError,'unambiguous'):native_physics.shape_region_permutation({},dict(node=0),payload)

    def test_failed_bitmap_is_isolated_only_for_explicit_object_batches(self):
        from port_environment import native_validation
        images=[dict(source_bitmap='a',destination='a.tif'),dict(source_bitmap='b',destination='b.tif')]
        report=dict(bitmap_builds=images)
        with patch.object(native_validation,'bitmap',side_effect=[ValueError('pixel mismatch'),dict(source='b#0')]):
            native_validation.bitmaps({},None,report,dict(defer_material_failures=True))
        self.assertEqual(report['native_bitmap_readback'],[dict(source='b#0')])
        self.assertEqual(report['native_bitmap_failures'][0]['source'],'a#0')
        with patch.object(native_validation,'bitmap',side_effect=ValueError('pixel mismatch')):
            with self.assertRaisesRegex(ValueError,'pixel mismatch'):native_validation.bitmaps({},None,dict(bitmap_builds=images),{})

    def test_physics_body_mapping_rejects_ambiguous_source_nodes(self):
        from port_environment.native_physics import source_bodies
        def block(name,rows):return dict(name=name,type='block',elements=[dict(fields=r,source_index=i) for i,r in enumerate(rows)])
        def field(name,value):return dict(name=name,type='short block index',value=value)
        nodes=block('nodes',[[dict(name='name',type='string id',value='arm')]])
        body=[field('node',0),field('region',-1),field('permutattion',-1)]
        self.assertEqual(list(source_bodies([nodes,block('rigid bodies',[body])])),[('arm',None,None)])
        with self.assertRaisesRegex(ValueError,'Ambiguous'):source_bodies([nodes,block('rigid bodies',[body,body])])
        body[0]['value']=1
        with self.assertRaisesRegex(ValueError,'Invalid'):source_bodies([nodes,block('rigid bodies',[body])])

    def test_ambiguous_dependency_is_rejected(self):
        reference=dict(name='model',value=dict(path='x/a',extension='model'))
        with self.assertRaisesRegex(ValueError,'Ambiguous'):
            object_ir.dependency(dict(fields=[reference,dict(name='nested',fields=[reference])]),'model')

    def test_flags_use_names_instead_of_source_ordinals(self):
        values={n:False for n in ('unused','lock transform to env. object')}
        native=SimpleNamespace(Items=[SimpleNamespace(FlagName=n) for n in values],SetBit=values.__setitem__,TestBit=values.__getitem__)
        source=dict(type='long flags',value=dict(value=4,set_bits=[[2,'lock transform to env. object']]))
        tags.write(native,source)
        self.assertFalse(values['unused'])
        self.assertTrue(values['lock transform to env. object'])

    def test_native_regular_flags_are_not_block_flags(self):
        from port_environment.native_zones import mask,write_mask
        target=SimpleNamespace(RawValue=0,BitCount=16,Items=[])
        write_mask(target,5)
        self.assertEqual(mask(target),5)

    def test_native_animation_spaces_do_not_allow_windows_aliases(self):
        from port_environment.paths import relative
        self.assertEqual(str(relative('export/animations/device position.gr2',allow_spaces=True)),
            'export/animations/device position.gr2')
        for path in ('../device position.gr2','CON .gr2','device.gr2 ','/device.gr2'):
            with self.assertRaises(ValueError):relative(path,allow_spaces=True)

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

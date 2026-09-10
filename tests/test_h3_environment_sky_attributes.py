"""Synthetic sky color regressions; no editing kit or proprietary asset needed."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment.sky_attributes import recover,draw_meshes,_strip,native_color_readback


def fixture():
    root=ET.Element('tag')
    def field(parent,name,value):ET.SubElement(parent,'field',name=name,value=str(value))
    def block(parent,name,rows):
        b=ET.SubElement(parent,'block',name=name,value='synthetic,'+str(len(rows)))
        for i,fn in enumerate(rows):fn(ET.SubElement(b,'element',index=str(i)))
    vertices=[dict(position=[0,0,0],normal=[0,0,1],uvs=[[0,1]],color=None),
              dict(position=[100,0,0],normal=[0,0,1],uvs=[[1,1]],color=None),
              dict(position=[0,100,0],normal=[0,0,1],uvs=[[0,0]],color=None)]
    mesh=dict(vertices=vertices+deepcopy(vertices),triangles=[dict(vertices=[0,1,2],material=0),dict(vertices=[3,4,5],material=1)],
              materials=[dict(name='sky',label='(1) base 00'),dict(name='sky',label='(2) base 01')],nodes=[],markers=[])
    block(root,'instance placements',[])
    def bounds(e):
        for n,v in [('position bounds 0','0,1,0'),('position bounds 1','1,0,1'),('texcoord bounds 0','0,1'),('texcoord bounds 1','0,1')]:field(e,n,v)
    block(root,'compression info',[bounds])
    block(root,'materials',[lambda e:field(e,'render method','synthetic/sky,rmsh')])
    def region(e,i):
        field(e,'name',f'{i:02}')
        def perm(p):
            for n,v in [('name','base'),('mesh index',i),('mesh count',1)]:field(p,n,v)
        block(e,'permutations',[perm])
    block(root,'regions',[lambda e:region(e,0),lambda e:region(e,1)])
    def metadata(e,i):
        field(e,'mesh flags',3 if i==0 else 2);field(e,'index buffer type','triangle strip')
        def part(p):
            for n,v in [('render method index',0),('index start',0),('index count',3)]:field(p,n,v)
        block(e,'parts',[part])
    block(root,'meshes',[lambda e:metadata(e,0),lambda e:metadata(e,1)])
    def raw(e,i):
        def vertex(e,j):
            v=vertices[j]
            for n,x in [('position',[p/100 for p in v['position']]),('normal',v['normal']),('texcoord',[v['uvs'][0][0],1-v['uvs'][0][1]]),
                        ('vertex color',[.1*(j+1),.2,.3] if i==0 else [-65536]*3)]:field(e,n,','.join(map(str,x)))
        block(e,'raw vertices',[lambda e,j=j:vertex(e,j) for j in range(3)])
        block(e,'raw indices',[lambda e,j=j:field(e,'word',j) for j in range(3)])
    block(root,'per mesh temporary',[lambda e:raw(e,0),lambda e:raw(e,1)])
    return mesh,root


class SkyAttributes(unittest.TestCase):
    def test_authored_color_and_uncolored_groups_remain_distinct(self):
        mesh,root=fixture();before=deepcopy(mesh);out=recover(mesh,root)
        self.assertEqual(mesh,before)
        self.assertEqual(out['triangles'],mesh['triangles'])
        self.assertEqual(out['vertices'][0]['color'],[.1,.2,.3])
        self.assertIsNone(out['vertices'][3]['color'])
        groups=list(draw_meshes(out))
        self.assertEqual([g['region_name'] for g,_ in groups],['00','01'])
        self.assertTrue(all(v['color'] is not None for v in groups[0][1]['vertices']))
        self.assertTrue(all(v['color'] is None for v in groups[1][1]['vertices']))

    def test_authored_black_is_preserved(self):
        mesh,root=fixture()
        root.find('.//field[@name="vertex color"]').set('value','0,0,0')
        self.assertEqual(recover(mesh,root)['vertices'][0]['color'],[0,0,0])

    def test_color_flag_cannot_turn_an_unset_sentinel_into_color(self):
        mesh,root=fixture()
        root.find('.//field[@name="vertex color"]').set('value','-65536,-65536,-65536')
        with self.assertRaisesRegex(ValueError,'color'):recover(mesh,root)

    def test_changed_geometry_cannot_receive_unrelated_source_colors(self):
        mesh,root=fixture();mesh['vertices'][0]['position'][0]=50
        with self.assertRaisesRegex(ValueError,'correspondence'):recover(mesh,root)

    def test_every_triangle_must_balance(self):
        mesh,root=fixture();mesh['triangles'].append(deepcopy(mesh['triangles'][0]))
        with self.assertRaisesRegex(ValueError,'every decoded'):recover(mesh,root)

    def test_material_correspondence_is_required(self):
        mesh,root=fixture();mesh['triangles'][0]['material']=1
        with self.assertRaisesRegex(ValueError,'material correspondence'):recover(mesh,root)

    def test_strip_uses_pinned_decoder_corner_order_through_degenerates(self):
        self.assertEqual(list(_strip([0,1,2,3,3,4,5])),[(0,1,2),(1,3,2),(3,4,5)])

    def test_native_readback_rejects_lost_authored_colors(self):
        mesh,source=fixture();groups=recover(mesh,source)['source_draw_groups'];target=deepcopy(source)
        rows=native_color_readback(source,target,groups)
        self.assertEqual(rows[0]['maximum_rgb_error'],0)
        self.assertEqual(rows[1]['status'],'NO_SOURCE_COLOR_ATTRIBUTE')
        target.find('.//field[@name="vertex color"]').set('value','0,0,0')
        with self.assertRaisesRegex(ValueError,'colors differ'):native_color_readback(source,target,groups)

    def test_native_readback_rejects_lost_sky_mesh(self):
        mesh,source=fixture();groups=recover(mesh,source)['source_draw_groups']
        with self.assertRaisesRegex(ValueError,'mesh count'):native_color_readback(source,source,groups[:-1])


if __name__=='__main__':unittest.main()

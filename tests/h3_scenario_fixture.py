"""Synthetic BSPs and authored-hint field trees, not shipped Halo assets."""
from copy import deepcopy
import json
from pathlib import Path

SCENARIO = 'levels/solo/fixture/fixture.scenario'
BSP = 'levels/solo/fixture/shared.bsp.scenario_structure_bsp'


def scene():
    return dict(format='foundry.h3-scene', version=1, game='halo3_mcc', source_tag=SCENARIO,
        units='ass_100_per_world_unit', inventory='scenario.h3inspect.json', destination_tags_written=False,
        geometry_requested=True, bsp_entries=[dict(index=0, source_tag=BSP, status='extracted',
        geometry='geometry/bsp_0000.json', diagnostics=[])], shader_paths=['objects/test/test.shader'], limitations=[])


def instance(identity, definition, parent=-1, position=None, **kwargs):
    row = dict(id=identity, object=definition, parent=parent, name=f'placement_{identity}', inheritance_flag=0,
        position=position or [0, 0, 0], rotation=[1, 0, 0, 0], scale=1,
        pivot_position=[0, 0, 0], pivot_rotation=[1, 0, 0, 0], pivot_scale=1, bone_groups=[])
    row.update(kwargs)
    return row


def bsp():
    vertices = [dict(position=p, normal=[0, .6, .8], color=[.1, .3, .7], weights=[],
                     uvs=[[u, v, w], [2*u, 2*v, 7]])
                for p, u, v, w in [([0,0,0],0,0,3), ([100,0,0],1,0,4), ([0,100,0],0,1,5)]]
    return dict(format='foundry.h3-bsp', version=1, source_tag=BSP, bsp_index=0, units='ass_100_per_world_unit',
        materials=[dict(slot=i, name='same', lightmap_variant='', ass_metadata=[],
                   source_shader=shader, destination_shader=None)
                   for i, shader in enumerate(['objects/test/test.shader', 'other/test.shader'])],
        objects=[dict(id=0, kind='mesh', xref_path='', xref_object='', vertices=vertices,
                      triangles=[dict(material=1, vertices=[0,1,2])])],
        instances=[instance(2,0,0,[200,0,0],scale=-2), instance(1,0,0,[100,0,0]), instance(0,-1)], limitations=[])


class Fields:
    def __init__(self): self.rows = []; self.ordinals = {}
    def add(self, parent, name, value=None, kind='value', field_type='short block index', **extra):
        ordinal = self.ordinals.get(parent, 0); self.ordinals[parent] = ordinal + 1
        address = (parent + '/' if parent else '') + f'{name}#{ordinal}'
        row = dict(address=address, name=name, raw_name=name, ordinal=ordinal, type=field_type, kind=kind, **extra)
        if kind == 'value': row['value'] = value
        self.rows.append(row)
        return address
    def block(self, parent, name, count=1): return self.add(parent,name,kind='block',field_type='block',count=count)
    def point(self,parent,name,position): return self.add(parent,name,{'values':position,'bits':[0,0,0]},field_type='real point 3d')
    def element(self,address,index=0): return f'{address}[{index}]'


def inventory():
    f = Fields(); h=f.element(f.block('', 'ai user hint data'))
    line=f.element(f.block(h,'line segment geometry'))
    f.add(line,'Flags',{'value':1,'set_bits':[[0,'bidirectional']]},field_type='long flags')
    for i, position in enumerate(([0,0,0],[2,0,0])):
        f.point(line,f'Point {i}',position);f.add(line,f'reference frame {i}',-1);f.add(line,f'structure bsp {i}',0)
    giant=f.element(f.block(h,'giant hints'))
    sector=f.element(f.block(giant,'giant sector hints')); points=f.block(sector,'points',3)
    for i,p in enumerate(([0,0,0],[2,0,0],[0,2,0])):
        parent=f.element(points,i);f.point(parent,'point',p);f.add(parent,'reference frame',-1);f.add(parent,'structure bsp',0)
    rail=f.element(f.block(giant,'giant rail hints'));f.add(rail,'geometry index',0)
    zone=f.element(f.block('','zones'));f.add(zone,'name','scarab_zone',field_type='string')
    f.add(zone,'flags',{'value':32,'set_bits':[[5,'giants zone']]},field_type='long flags')
    area=f.element(f.block(zone,'areas'));f.add(area,'name','platform',field_type='string')
    fire=f.element(f.block(zone,'firing positions'));f.point(fire,'position (local)',[1,2,3]);f.add(fire,'reference frame',-1);f.add(fire,'bsp index',0);f.add(fire,'area',0)
    script=f.element(f.block('','scripting data'));ps=f.element(f.block(script,'point sets'))
    f.add(ps,'name','ps_scarab',field_type='string');f.add(ps,'bsp index',0)
    point=f.element(f.block(ps,'points'));f.add(point,'name','p0',field_type='string');f.point(point,'position',[3,2,1]);f.add(point,'reference frame',-1)
    return dict(format='foundry.h3-scenario-inspection',version=1,source_tag=SCENARIO,source_group='scnr',
        coordinate_encoding='source_world_units_unmodified',destination_tags_written=False,
        scope=dict(bsp_dependencies_loaded=False,resource_payloads_decoded=False,scripts_executed=False,lossless_tag_roundtrip=False),
        records=f.rows,references=[],diagnostics=[])


def write_bundle(directory, with_blob=False):
    directory=Path(directory);(directory/'geometry').mkdir(exist_ok=True);(directory/'blobs').mkdir(exist_ok=True)
    data=inventory()
    if with_blob:
        data['records'].append(dict(address='opaque#99',name='opaque',raw_name='opaque',ordinal=99,type='data',kind='data',file='blobs/000000.bin',bytes=4))
        (directory/'blobs/000000.bin').write_bytes(b'\x00\x01\xfe\xff')
    for name,value in [('scene.h3scene.json',scene()),('scenario.h3inspect.json',data),('geometry/bsp_0000.json',bsp())]:
        (directory/name).write_text(json.dumps(value))
    return scene(),data

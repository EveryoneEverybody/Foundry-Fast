"""Synthetic source placements, sharing palettes without sharing instance state."""
from h3_scenario_fixture import Fields, inventory


def content_inventory():
    data = inventory()
    f = Fields()
    # Keep root ordinals distinct from the existing hint fixture.
    f.ordinals[''] = 100
    names = f.block('', 'object names', 6)
    for i, name in enumerate(['gate_a','gate_b','gate_variant','machine_a','machine_b','crate_a']):
        f.add(f.element(names,i),'name',name,field_type='string')
    folders = f.block('','editor folders',2)
    for i, name in enumerate(['Scarab encounter','Props']):
        p = f.element(folders,i); f.add(p,'name',name,field_type='string'); f.add(p,'parent folder',i-1)
    for category,palette,extension,offset,count in [('scenery','scenery','scenery',0,3),('machines','machine','device_machine',3,2),('crates','crate','crate',5,1)]:
        p=f.element(f.block('',palette+' palette'))
        f.add(p,'name',dict(path='objects/test/panel',extension=extension),field_type='tag reference')
        placements=f.block('',category,count)
        for i in range(count):
            p=f.element(placements,i);f.add(p,'type',0);f.add(p,'name',offset+i)
            ob=f.add(p,'object data',kind='struct',field_type='struct')
            f.point(ob,'position',[10+i,20,30]);f.point(ob,'rotation',[.5,.25,-.1])
            f.add(ob,'scale',dict(values=[0. if i==0 else 2.],bits=[0]),field_type='real')
            f.add(ob,'editor folder',1)
            parent=f.add(ob,'parent id',kind='struct',field_type='struct');f.add(parent,'parent object',-1)
            perm=f.add(p,'permutation data',kind='struct',field_type='struct')
            f.add(perm,'variant name','alternate' if i==2 else 'default',field_type='string id')
            f.add(perm,'active change colors',dict(value=1,set_bits=[[0,'primary']]))
    t=f.element(f.block('','trigger volumes'));f.add(t,'name','Scarab arrival');f.add(t,'object name',-1)
    f.point(t,'position',[1,2,3]);f.point(t,'forward',[1,0,0]);f.point(t,'up',[0,0,1]);f.point(t,'extents',[2,4,6])
    for category,key,values in [('player starting locations','facing',[.25]),('cutscene flags','facing',[.25,.5]),('cutscene camera points','orientation',[.25,.5,.75])]:
        t=f.element(f.block('',category));f.add(t,'name','Authored '+category);f.point(t,'position',[1,2,3]);f.point(t,key,values)
    g=f.element(f.block('','squad groups'));f.add(g,'name','Scarab support');f.add(g,'parent',-1)
    s=f.element(f.block('','squads'));f.add(s,'name','Driver');f.add(s,'parent',0);f.add(s,'initial objective',0)
    team=f.element(f.block(s,'fire-teams'));start=f.element(f.block(team,'starting locations'))
    f.add(start,'name','Driver start');f.point(start,'position',[1,2,3]);f.add(start,'reference frame',-1);f.point(start,'facing (yaw, pitch)',[.1,.2])
    o=f.element(f.block('','ai objectives'));f.add(o,'name','Scarab objective')
    task=f.element(f.block(o,'tasks'));f.add(task,'name','Boarding');area=f.element(f.block(task,'areas'));f.add(area,'zone',0);f.add(area,'area',0)
    z=f.element(f.block('','designer zones'));f.add(z,'name','Scarab designer zone');p=f.element(f.block(z,'giants'));f.add(p,'palette index',0)
    data['records'].extend(f.rows)
    return data

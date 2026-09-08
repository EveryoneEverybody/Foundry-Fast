"""Source-indexed scenario objects; compiled resources are never copied."""
from copy import deepcopy
import math
from . import scenario_ir,native_object_tags,native_zones

SUPPORTED=('scenery','crates','machines','controls')
KINDS=dict(scenery='scenery',crates='crate',machines='machine',controls='control')


def first(rows,name):
    return next((r for r in rows if r['name']==name),None)


def section(rows,name):
    start=next(i for i,r in enumerate(rows) if r['name']==name and r['type']=='struct')+1
    end=next((i for i in range(start,len(rows)) if rows[i]['type']=='struct'),len(rows))
    return rows[start:end]


def plan(inventory,compiled,objects):
    """Keep sparse palette identities and close parent dependencies explicitly."""
    result=deepcopy(inventory)
    for family in SUPPORTED:
        group=result['families'][family];palette_map={}
        for row in group['palette']:
            source=row['source_tag']
            if source in compiled:
                row.update(target_index=len(palette_map),target_tag=compiled[source]['target_tag'],native_status='NATIVE_COMPILED')
                palette_map[row['source_index']]=row['target_index']
            else:
                evidence=objects.get(source,{})
                row.update(native_status='DEFERRED',reason=evidence.get('reason') or evidence.get('blockers') or ['Native dependency was not compiled'])
        for row in group['placements']:
            if row['source_problems'] or row['source_palette_index'] not in palette_map:
                palette=next((p for p in group['palette'] if p['source_index']==row['source_palette_index']),{})
                row.update(native_status='DEFERRED',reason=row['source_problems'] or palette.get('reason') or 'Native dependency absent')
            else:
                row.update(native_status='READY',target_palette_index=palette_map[row['source_palette_index']])
                if row['stored_pose_count']:
                    row.update(classification='STATICIZED_MVP',stored_pose_status='SOURCE_BIND_POSE',
                        fidelity_loss='Packed H3 stored-pose codec is unverified; source bind pose used, exact packed source retained, no runtime bytes copied')
        group['translated_palette_count']=len(palette_map)
        group['deferred_palette_count']=len(group['palette'])-len(palette_map)
    while True:
        available={r['source_object_name_index'] for f in SUPPORTED for r in result['families'][f]['placements']
                   if r['native_status']=='READY' and r['source_object_name_index']>=0}
        changed=False
        for f in SUPPORTED:
            for r in result['families'][f]['placements']:
                parent=r['parent']['source_name_index']
                if r['native_status']=='READY' and parent>=0 and parent not in available:
                    r.update(native_status='DEFERRED',reason='Parent object is deferred; original attachment preserved in IR')
                    changed=True
        if not changed:break
    for f in SUPPORTED:
        group=result['families'][f];ready=[r for r in group['placements'] if r['native_status']=='READY']
        for i,r in enumerate(ready):r['target_index']=i
        group.update(translated_instance_count=len(ready),deferred_instance_count=len(group['placements'])-len(ready))
    return result


def xml_write(target,row):
    """Translate XML authoring types through actual native names and values."""
    kind=row['type'];value=row['value']
    if 'block index' in kind:
        value=int(value.rsplit(',',1)[-1]);target.Value=value
        if int(target.Value)!=value:raise ValueError('Native index readback differs')
        return value
    if 'block flags' in kind:
        value=int(value);native_zones.write_mask(target,value)
        if native_zones.mask(target)!=value:raise ValueError('Native membership readback differs')
        return value
    if 'flags' in kind:
        # Enum bit orders differ between H3 and Reach, including placement
        # flags. Named flags are required unless the value is empty.
        names=row.get('set_flags',[])
        if int(value) and not names:raise ValueError('Source nonzero flags lack named evidence: '+row['name'])
        value=dict(set_bits=list(enumerate(names)))
    elif 'enum' in kind:value=dict(name=value)
    elif kind in {'string','string id','long string'}:pass
    elif 'integer' in kind:value=int(value)
    elif ',' in value:value=[float(v) for v in value.split(',')]
    else:value=float(value)
    return native_object_tags.write(target,dict(name=row['name'],type=kind,value=value))


def copy(rows,target,names):
    out=[]
    for name in names:
        row=first(rows,name)
        if row is not None:out.append(dict(field=name,result=xml_write(native_object_tags.select(target,name),row)))
    return out


def verify_xml(rows,target,names):
    """Read authoring values back after reopening; never mutate during validation."""
    from .native_validation import close
    for name in names:
        row=first(rows,name)
        if row is None:continue
        field=native_object_tags.select(target,name);kind=row['type'];expected=row['value']
        if 'block index' in kind:
            actual=int(field.Value);expected=int(expected.rsplit(',',1)[-1])
        elif 'block flags' in kind:actual=native_zones.mask(field);expected=int(expected)
        elif 'flags' in kind:
            actual=sorted(native_object_tags.normalized(i.FlagName) for i in field.Items if field.TestBit(i.FlagName))
            expected=sorted(native_object_tags.normalized(n) for n in row.get('set_flags',[]))
        elif 'enum' in kind:
            actual=native_object_tags.normalized(field.Items[field.Value].EnumName)
            expected=native_object_tags.normalized(expected)
        elif kind in {'string','string id','long string'}:actual=field.GetStringData()
        else:
            expected=[float(v) for v in expected.split(',')] if ',' in expected else float(expected)
            actual=list(field.Data) if isinstance(expected,list) else field.Data
            close(actual,expected,'scenario '+name);continue
        if actual!=expected:raise ValueError('Native scenario field differs: '+name)


def object_element(element,row):
    s=element.SelectField;records=row['source_records']
    s('type').Value=row['target_palette_index'];s('name').Value=row['source_object_name_index']
    data=s('object data').Elements[0]
    flags=deepcopy(first(records,'placement flags'))
    # No packed H3 runtime orientations enter native tags. The visible default
    # skeleton and exact world transform remain source-authored.
    if row['stored_pose_count']:
        flags['set_flags']=[n for n in flags['set_flags'] if native_object_tags.normalized(n)!='store orientations']
        if not flags['set_flags']:flags['value']='0'
    xml_write(data.SelectField('placement flags'),flags)
    data.SelectField('position').Data=row['position_world']
    data.SelectField('rotation').Data=row['rotation_degrees']
    data.SelectField('scale').Data=row['scale']
    copy(records,data,('bsp policy','manual bsp flags','transform flags','light airprobe name','can attach to bsp flags'))
    data.SelectField('editor folder').Value=-1
    oid=data.SelectField('object id').Elements[0]
    copy(section(records,'object id'),oid,('unique id','origin bsp index','type','source'))
    copy(section(records,'parent id'),data.SelectField('parent id').Elements[0],('parent object','parent marker','connection marker'))
    permutation=s('permutation data').Elements[0]
    copy(records,permutation,('variant name',))
    active=first(records,'active change colors')
    native_zones.write_mask(permutation.SelectField('active change colors'),int(active['value']))
    # No supported 040_voi placement enables a color override. Keep inactive
    # packed values in the IR until a native pixel-color writer is validated.
    if int(active['value']):raise ValueError('Active placement color overrides need a verified native color adapter')
    family=row['family']
    if family in {'machines','controls'}:
        copy(section(records,'device data'),s('device data').Elements[0],('power group','position group','flags'))
        name='machine data' if family=='machines' else 'control data'
        copy(section(records,name),s(name).Elements[0],('flags','pathfinding policy','health station charges'))
    elif family=='scenery':
        copy(section(records,'scenery data'),s('scenery data').Elements[0],('Pathfinding policy','Lightmapping policy'))
        s('scenery data').Elements[0].SelectField('ai spawning squad').Value=-1
    return dict(source_index=row['source_index'],target_index=row['target_index'],status='AUTHORED')


def configure(tag,translation,environment,*,defer_zone_switches=False):
    s=tag.tag.SelectField
    report=dict(families={},runtime_status='NOT_TESTED',designer_zones=[])
    names=s('object names');names.RemoveAllElements()
    for row in translation['object_names']:
        e=names.AddElement();e.SelectField('name').SetStringData(row['name'])
        e.SelectField('object_type').Value=-1;e.SelectField('scenario_datum_index').Value=-1
    groups=s('device groups');groups.RemoveAllElements()
    for row in translation['device_groups']:
        e=groups.AddElement();copy(row['source_records'],e,('name','initial value','flags'))
        e.SelectField('editor folder').Value=-1
    for family in SUPPORTED:
        group=translation['families'][family];palette=s(scenario_ir.FAMILIES[family][0]);palette.RemoveAllElements()
        for row in group['palette']:
            if row['native_status']=='NATIVE_COMPILED':palette.AddElement().SelectField('name').Path=tag._TagPath_from_string(row['target_tag'])
        block=s(family);block.RemoveAllElements()
        report['families'][family]=[]
        for row in group['placements']:
            if row['native_status']!='READY':continue
            element=block.AddElement()
            report['families'][family].append(object_element(element,row))
            ni=row['source_object_name_index']
            if ni>=0:
                e=names.Elements[ni]
                # Object-name type uses the same native object-kind table as
                # the typed placement ID; source numeric kind is never reused.
                kind=element.SelectField('object data[0]/object id[0]/type').Value
                e.SelectField('object_type').Value=kind;e.SelectField('scenario_datum_index').Value=row['target_index']
    for zone in environment['selection']['designer_zones']:
        e=s('designer zones').Elements[zone['target_index']];z=dict(name=zone['name'],translated=[],deferred=[])
        for source in zone['source_records']:
            if source['kind']!='block':continue
            family=next((f for f in SUPPORTED if KINDS[f]==source['name']),None)
            if not family:
                if source['count']:z['deferred'].append(source)
                continue
            native=e.SelectField('Block:'+source['name']);native.RemoveAllElements()
            mapping={r['source_index']:r['target_index'] for r in translation['families'][family]['palette'] if r['native_status']=='NATIVE_COMPILED'}
            for record in source['elements']:
                index=int(first(record,'palette index')['value'].rsplit(',',1)[-1])
                if index in mapping:
                    native.AddElement().SelectField('palette index').Value=mapping[index]
                    z['translated'].append(dict(family=family,source_palette_index=index,target_palette_index=mapping[index]))
                else:z['deferred'].append(dict(family=family,source_palette_index=index,reason='Native dependency deferred'))
        report['designer_zones'].append(z)
    starts=s('player starting locations');starts.RemoveAllElements()
    for row in translation['starting_locations']:
        e=starts.AddElement();copy(row,e,('position','facing','pitch'));e.SelectField('editor folder').Value=-1
    report['starts']=dict(count=starts.Elements.Count,source=translation['starting_locations'],
        target_profile='Existing native test-player scaffold; H3 player type and weapon gameplay dependencies deferred')
    report['zone_switch_authoring']=zone_switches(tag,translation,defer_switches=defer_zone_switches)
    tag.tag_has_changes=True;tag.tag.Save()
    return report


def zone_switches(tag,translation,*,defer_switches=False):
    """Preserve static authored boxes and exact zone-switch index relations."""
    volumes=tag.tag.SelectField('trigger volumes');volumes.RemoveAllElements()
    mapping={};report=dict(volumes=[],deferred_volumes=[],switches=[],deferred_switches=[])
    for index,row in enumerate(translation['trigger_volumes']):
        parent=int(first(row,'object name')['value'].rsplit(',',1)[-1])
        if parent>=0:
            report['deferred_volumes'].append(dict(source_index=index,reason='Moving object-relative trigger requires native attachment validation'))
            continue
        e=volumes.AddElement();mapping[index]=e.ElementIndex
        e.SelectField('type').SetValue('bounding box')
        copy(row,e,('name','node name','forward','up','position','extents'))
        e.SelectField('object name').Value=-1;e.SelectField('editor folder').Value=-1
        e.SelectField('kill trigger volume').Value=-1
        report['volumes'].append(dict(source_index=index,target_index=e.ElementIndex,name=first(row,'name')['value'],
            classification='NATIVE_TRANSFORM',runtime_fields='Regenerated by Reach; H3 runtime indices/planes not copied'))
    block=tag.tag.SelectField('zone set switch trigger volumes');block.RemoveAllElements()
    for index,row in enumerate(translation['zone_switch_triggers']):
        source=int(first(row,'trigger volume')['value'].rsplit(',',1)[-1])
        if defer_switches:
            report['deferred_switches'].append(dict(source_index=index,source_records=row,
                source_trigger=source,target_trigger=mapping.get(source),classification='RUNTIME_LATER',
                reason='Native persistence unverified: this Reach kit reopened an empty switch table after authoring all source records'))
            continue
        if source not in mapping:
            report['deferred_switches'].append(dict(source_index=index,reason='Trigger volume deferred'));continue
        e=block.AddElement();copy(row,e,('flags','begin zone set','commit zone set'))
        e.SelectField('trigger volume').Value=mapping[source]
        report['switches'].append(dict(source_index=index,target_index=e.ElementIndex,source_trigger=source,target_trigger=mapping[source],
            begin=int(e.SelectField('begin zone set').Value),commit=int(e.SelectField('commit zone set').Value)))
    return report


def validate(tag,translation,environment,*,defer_zone_switches=False):
    s=tag.tag.SelectField;result=dict(zone_sets=native_zones.readback(tag,environment),families={})
    for family in SUPPORTED:
        group=translation['families'][family];block=s(family)
        palette=s(scenario_ir.FAMILIES[family][0]).Elements
        expected_palette=[r for r in group['palette'] if r['native_status']=='NATIVE_COMPILED']
        if palette.Count!=len(expected_palette):raise ValueError('Native palette count differs: '+family)
        for e,row in zip(palette,expected_palette):
            path=e.SelectField('name').Path
            if path is None or str(path.RelativePathWithExtension).replace('\\','/')!=row['target_tag']:raise ValueError('Native palette dependency identity differs')
        if block.Elements.Count!=group['translated_instance_count']:raise ValueError('Native placement count differs: '+family)
        for row in group['placements']:
            if row['native_status']!='READY':continue
            e=block.Elements[row['target_index']];d=e.SelectField('object data').Elements[0]
            if int(e.SelectField('type').Value)!=row['target_palette_index'] or int(e.SelectField('name').Value)!=row['source_object_name_index']:
                raise ValueError('Native placement identity differs')
            for name,expected in [('position',row['position_world']),('rotation',row['rotation_degrees']),('scale',[row['scale']])]:
                value=d.SelectField(name).Data;actual=[value] if name=='scale' else list(value)
                if any(not math.isclose(a,b,abs_tol=2e-4,rel_tol=1e-6) for a,b in zip(actual,expected)):
                    raise ValueError('Native transform differs: '+name)
            if family in {'controls','machines'}:
                for name,value in row['device_groups'].items():
                    if int(e.SelectField('device data[0]/'+name).Value)!=value:raise ValueError('Native device relationship differs')
            verify_xml(section(row['source_records'],'parent id'),d.SelectField('parent id').Elements[0],('parent object','parent marker','connection marker'))
            verify_xml(row['source_records'],e.SelectField('permutation data').Elements[0],('variant name',))
        result['families'][family]=dict(palette=s(scenario_ir.FAMILIES[family][0]).Elements.Count,placements=block.Elements.Count)
    if s('player starting locations').Elements.Count!=len(translation['starting_locations']):raise ValueError('Native start count differs')
    for e,row in zip(s('player starting locations').Elements,translation['starting_locations']):verify_xml(row,e,('position','facing','pitch'))
    result['device_groups']=s('device groups').Elements.Count;result['object_names']=s('object names').Elements.Count
    if result['device_groups']!=len(translation['device_groups']) or result['object_names']!=len(translation['object_names']):raise ValueError('Native name/group count differs')
    for e,row in zip(s('device groups').Elements,translation['device_groups']):verify_xml(row['source_records'],e,('name','initial value','flags'))
    for e,row in zip(s('object names').Elements,translation['object_names']):
        if e.SelectField('name').GetStringData()!=row['name']:raise ValueError('Native object name identity differs')
    volumes=[(i,r) for i,r in enumerate(translation['trigger_volumes']) if int(first(r,'object name')['value'].rsplit(',',1)[-1])<0]
    if s('trigger volumes').Elements.Count!=len(volumes):raise ValueError('Native static trigger count differs')
    mapping={source:index for index,(source,_) in enumerate(volumes)}
    for e,(_,row) in zip(s('trigger volumes').Elements,volumes):verify_xml(row,e,('name','node name','forward','up','position','extents'))
    switches=[r for r in translation['zone_switch_triggers'] if int(first(r,'trigger volume')['value'].rsplit(',',1)[-1]) in mapping]
    if defer_zone_switches:
        result['deferred_zone_switch_triggers']=len(switches);switches=[]
    if s('zone set switch trigger volumes').Elements.Count!=len(switches):raise ValueError('Native zone switch count differs')
    for e,row in zip(s('zone set switch trigger volumes').Elements,switches):
        verify_xml(row,e,('flags','begin zone set','commit zone set'))
        if int(e.SelectField('trigger volume').Value)!=mapping[int(first(row,'trigger volume')['value'].rsplit(',',1)[-1])]:raise ValueError('Native zone switch trigger identity differs')
    result['static_trigger_volumes']=len(volumes);result['zone_switch_triggers']=len(switches)
    for zone in environment['selection']['designer_zones']:
        e=s('designer zones').Elements[zone['target_index']]
        for source in zone['source_records']:
            if source['kind']!='block':continue
            family=next((f for f in SUPPORTED if KINDS[f]==source['name']),None)
            if family is None:continue
            mapping={r['source_index']:r['target_index'] for r in translation['families'][family]['palette'] if r['native_status']=='NATIVE_COMPILED'}
            indices=[int(first(r,'palette index')['value'].rsplit(',',1)[-1]) for r in source['elements']]
            expected=[mapping[i] for i in indices if i in mapping]
            actual=[int(r.SelectField('palette index').Value) for r in e.SelectField('Block:'+source['name']).Elements]
            if actual!=expected:raise ValueError('Native designer-zone palette membership differs: '+zone['name']+'/'+family)
    result['designer_zone_palette_membership']='VERIFIED'
    result['status']='NATIVE_PLACEMENT_READBACK_VERIFIED';result['runtime_status']='NOT_TESTED'
    if defer_zone_switches:result['zone_switch_persistence']='DEFERRED; source records retained in the translation and authoring report'
    return result

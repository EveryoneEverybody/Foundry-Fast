"""Preserve loose physics authoring by node/region/permutation identity."""
from . import object_ir as ir, native_object_tags as fields


BODY_FIELDS=('flags','motion type','size','inertia tensor scale','linear damping','angular damping',
             'center off mass offset','mass')
ROOT_FIELDS=('mass','low freq. deactivation scale','high freq. deactivation scale')


def elements(rows,name):return (ir.field(rows,name) or {}).get('elements',[])
def value(rows,name):return ir.scalar(ir.field(rows,name))


def source_bodies(rows):
    nodes=elements(rows,'nodes');regions=elements(rows,'regions');result={}
    for body in elements(rows,'rigid bodies'):
        data=body['fields'];node=value(data,'node');region=value(data,'region');perm=value(data,'permutattion')
        if node < -1 or node>=len(nodes) or region < -1 or region>=len(regions):raise ValueError('Invalid source rigid-body identity')
        permutations=elements(regions[region]['fields'],'permutations') if region>=0 else []
        if perm < -1 or perm>=len(permutations):raise ValueError('Invalid source physics permutation')
        key=(value(nodes[node]['fields'],'name') if node>=0 else None,
             value(regions[region]['fields'],'name') if region>=0 else None,
             value(permutations[perm]['fields'],'name') if perm>=0 else None)
        if key in result:raise ValueError('Ambiguous source rigid-body identity')
        result[key]=body
    return result


def native_bodies(tag):
    nodes=tag.SelectField('nodes').Elements;regions=tag.SelectField('regions').Elements;result={}
    for body in tag.SelectField('rigid bodies').Elements:
        node=int(body.SelectField('node').Value);region=int(body.SelectField('region').Value);perm=int(body.SelectField('permutattion').Value)
        if node < -1 or node>=nodes.Count or region < -1 or region>=regions.Count:raise ValueError('Invalid native rigid-body identity')
        permutations=regions[region].SelectField('permutations').Elements if region>=0 else []
        count=permutations.Count if hasattr(permutations,'Count') else len(permutations)
        if perm < -1 or perm>=count:raise ValueError('Invalid native physics permutation')
        key=(nodes[node].SelectField('name').GetStringData() if node>=0 else None,
             regions[region].SelectField('name').GetStringData() if region>=0 else None,
             permutations[perm].SelectField('name').GetStringData() if perm>=0 else None)
        if key in result:raise ValueError('Ambiguous native rigid-body identity')
        result[key]=body
    return result


def shape_region_permutation(source,shape,payload):
    """Use the decoded physics node to identify one authored rigid body."""
    node=shape['node'];nodes=payload['physics']['nodes']
    if node < -1 or node>=len(nodes):raise ValueError('Invalid physics shape node')
    name=nodes[node]['name'] if node>=0 else None
    matches=[k for k in source_bodies(source) if k[0]==name]
    if len(matches)!=1:raise ValueError('Physics shape requires an unambiguous source body association')
    _,region,permutation=matches[0]
    if region is None or permutation is None:raise ValueError('Unassigned source physics region/permutation needs a separate authoring adapter')
    return region,permutation


def author(row):
    from io_scene_foundry.managed_blam import Tag
    source=row['object_ir']['physics_authoring'];expected=source_bodies(source)
    report=dict(bodies=[],materials=[],fields=[],runtime_status='NOT_TESTED',
        runtime_resource_policy='Tool rebuilds shapes, bounds, centers/inertia tensors and Havok resources; no H3 runtime bytes copied')
    with Tag(path=row['target_base']+'.physics_model',tag_must_exist=True) as tag:
        actual=native_bodies(tag.tag)
        if expected.keys()!=actual.keys():raise ValueError('Native/source rigid-body identities differ')
        fields.copy_fields(source,tag.tag,ROOT_FIELDS,report['fields'])
        for key,body in expected.items():
            result=dict(identity=key,source_index=body['source_index'],native_index=actual[key].ElementIndex,fields=[])
            fields.copy_fields(body['fields'],actual[key],BODY_FIELDS,result['fields'])
            report['bodies'].append(result)
        by_name={}
        for material in elements(source,'materials'):
            name=value(material['fields'],'name')
            if name in by_name:raise ValueError('Ambiguous source physics material name')
            by_name[name]=material
        for material in tag.tag.SelectField('materials').Elements:
            name=material.SelectField('name').GetStringData()
            if name not in by_name:raise ValueError('Native physics material identity differs: '+name)
            result=dict(name=name,fields=[])
            fields.copy_fields(by_name[name]['fields'],material,('global material name','flags','proxy collision group'),result['fields'])
            report['materials'].append(result)
        tag.tag_has_changes=True;tag.tag.Save()
    return report


def validate(tag,row):
    source=source_bodies(row['object_ir']['physics_authoring']);native=native_bodies(tag)
    if source.keys()!=native.keys():raise ValueError('Native/source physics identities differ on readback')
    rows=[]
    for identity,body in source.items():
        result=dict(identity=identity,fields={})
        for name in BODY_FIELDS:
            field=ir.field(body['fields'],name)
            if field is None:continue
            target=native[identity].SelectField(name);expected=ir.scalar(field)
            if 'enum' in field['type']:
                actual=str(target.Items[target.Value].EnumName);expected=field['value']['name']
                if fields.normalized(actual)!=fields.normalized(expected):raise ValueError('Native physics enum differs: '+name)
            elif 'flags' in field['type']:
                actual=sorted(fields.normalized(i.FlagName) for i in target.Items if target.TestBit(i.FlagName))
                expected=sorted(fields.normalized(n) for _,n in field['value']['set_bits'])
                if actual!=expected:raise ValueError('Native physics flags differ')
            else:
                from .native_validation import close
                actual=list(target.Data) if isinstance(expected,list) else target.Data
                close(actual,expected,'physics '+name)
            result['fields'][name]=actual
        rows.append(result)
    return dict(bodies=rows,status='AUTHORING_FIELDS_READBACK_VERIFIED',runtime_effective_mass='NOT_TESTED')

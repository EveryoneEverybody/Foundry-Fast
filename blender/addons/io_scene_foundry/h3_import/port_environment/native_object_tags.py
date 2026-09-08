"""Typed authoring and readback for the shared non-unit object dependencies."""
import math
import re
from . import object_ir


def normalized(name):
    return ' '.join(str(name).casefold().replace('_',' ').replace('-',' ').split())


def select(node,name):
    result=node.SelectField(name)
    if result is None:raise ValueError('Native field absent: '+name)
    return result


def source_struct(rows,name):
    row=object_ir.field(rows,name)
    if row is None or 'fields' not in row:raise ValueError('Source struct absent: '+name)
    return row['fields']


def write(target,source):
    kind=source['type'];value=object_ir.scalar(source)
    if 'flags' in kind:
        bits=source.get('value') or {}
        names={normalized(n) for _,n in bits.get('set_bits',[])}
        items=list(target.Items);native={normalized(i.FlagName if hasattr(i,'FlagName') else i.Name):i for i in items}
        if names-native.keys():raise ValueError('Unmapped native flags: '+str(sorted(names-native.keys())))
        for name,item in native.items():item.IsSet=name in names
        actual=sorted(name for name,item in native.items() if item.IsSet)
        if actual!=sorted(names):raise ValueError('Native flag readback differs')
        return dict(source=source,readback=actual,method='FLAG_NAMES')
    if 'enum' in kind:
        name=source['value']['name']
        choices={normalized(i.EnumName):i for i in target.Items}
        if normalized(name) not in choices:raise ValueError('Unmapped native enum name: '+name)
        item=choices[normalized(name)];target.Value=item.EnumIndex
        if int(target.Value)!=item.EnumIndex:raise ValueError('Native enum readback differs')
        return dict(source=source,readback=str(item.EnumName),method='ENUM_NAME')
    if kind in {'string id','string','long string'}:
        target.SetStringData(value or '')
        if target.GetStringData()!=(value or ''):raise ValueError('Native string readback differs')
        return dict(source=source,readback=target.GetStringData(),method='STRING_VALUE')
    if isinstance(value,str) and 'bounds' in kind:
        # Older pinned metadata displayed FractionBounds rather than its two
        # values. Parse that exact typed representation, never arbitrary code.
        match=re.fullmatch(r'FractionBounds\(Bounds \{ lower: ([-+\d.eE]+), upper: ([-+\d.eE]+) \}\)',value)
        if match:value=[float(v) for v in match.groups()]
    if isinstance(value,(int,float,list)):
        values=value if isinstance(value,list) else [value]
        if not all(isinstance(v,(float,int)) and math.isfinite(v) for v in values):raise ValueError('Nonfinite source numeric field')
        target.Data=value
        actual=list(target.Data) if isinstance(value,list) else target.Data
        out=actual if isinstance(actual,list) else [actual]
        if len(out)!=len(values) or any(not math.isclose(float(a),float(b),rel_tol=2e-5,abs_tol=1e-6) for a,b in zip(out,values)):
            raise ValueError('Native numeric readback differs: '+source['name'])
        return dict(source=source,readback=actual,method='NUMERIC_VALUE')
    raise ValueError('Unsupported source scalar field: '+source['name']+' '+kind)


def copy_fields(source,target,names,report,*,required=True):
    for name in names:
        row=object_ir.field(source,name)
        if row is None:continue
        try:report.append(dict(field=name,**write(select(target,name),row)))
        except (ValueError,AttributeError,TypeError) as exc:
            if required:raise
            report.append(dict(field=name,source=row,status='DEFERRED',reason=str(exc)))


DEVICE_FIELDS=('flags','power transition time','power acceleration time','position transition time','position acceleration time',
    'depowered position transition time','depowered position acceleration time','automatic activation radius')
OBJECT_FIELDS=('bounding radius','bounding offset','dynamic light sphere radius','dynamic light sphere offset')
MACHINE_FIELDS=('type','flags','door open time','door occlusion bounds','collision response','elevator node','pathfinding policy')
CONTROL_FIELDS=('type','triggers when','call value','action string')


def author(row,payload):
    from io_scene_foundry.managed_blam import Tag
    from io_scene_foundry.managed_blam.model import ModelTag
    report=dict(fields=[],model_variants=[],deferred_dependencies=[],runtime_status='NOT_TESTED')
    source=row['object_ir'];device=row['source_group'] in {'device_machine','device_control'}
    root=source['source_authoring'];base=source_struct(source_struct(root,'device'),'object') if device else source_struct(root,'object')
    with Tag(path=row['target_tag'],tag_must_exist=True) as tag:
        device_target=select(tag.tag,'Struct:device').Elements[0] if device else None
        target=select(device_target if device else tag.tag,'Struct:object').Elements[0]
        select(target,'model').Path=tag._TagPath_from_string(row['target_base']+'.model')
        copy_fields(base,target,OBJECT_FIELDS,report['fields'])
        acceleration=object_ir.field(base,'acceleration scale')
        if acceleration:
            for name in ('horizontal acceleration scale','vertical acceleration scale','angular acceleration scale'):
                report['fields'].append(dict(field=name,**write(select(target,name),acceleration),
                    translation='H3 isotropic acceleration scale expands to the three Reach axes'))
        copy_fields(base,target,('flags','default model variant','lightmap shadow mode','sweetener size'),report['fields'],required=False)
        if device:
            copy_fields(source_struct(root,'device'),device_target,DEVICE_FIELDS,report['fields'])
            copy_fields(root,tag.tag,MACHINE_FIELDS if row['source_group']=='device_machine' else CONTROL_FIELDS,report['fields'])
        tag.tag_has_changes=True;tag.tag.Save()
    with ModelTag(path=row['target_base']+'.model',tag_must_exist=True) as tag:
        tag.set_asset_paths()
        select(tag.tag,'imposter policy').SetValue('never')
        variants=tag.block_variants;variants.RemoveAllElements()
        for variant in payload['variants']:
            e=variants.AddElement();e.SelectField('name').SetStringData(variant['name'])
            for region in variant['regions']:
                reg=e.SelectField('regions').AddElement();reg.SelectField('name').SetStringData(region['name'])
                for perm in region['permutations']:
                    p=reg.SelectField('permutations').AddElement();p.SelectField('name').SetStringData(perm['name'])
                    if perm['flags']:
                        report.setdefault('fidelity_loss',[]).append('Variant permutation flags retained as source evidence; automatic random-state behavior deferred')
                    p.SelectField('probability').Data=perm['probability']
                    # State damage execution is outside this object milestone;
                    # preserve its source identities, author the source default.
                    if perm['states']:
                        report.setdefault('deferred_damage_states',[]).append(dict(variant=variant['name'],region=region['name'],permutation=perm['name'],states=perm['states']))
            if variant.get('children'):report['deferred_dependencies']+=variant['children']
            report['model_variants'].append(dict(name=variant['name'],regions=variant['regions'],status='DEFAULT_VARIANT_AUTHORED'))
        tag.tag_has_changes=True;tag.tag.Save()
    report['source_object_functions']=source['functions']
    report['function_status']='DEFERRED_OBJECT_FUNCTIONS; device power/position semantics authored independently'
    report['deferred_dependencies'] += [r for r in source['dependency_provenance'] if r['source_group'] not in
        {'model','render_model','collision_model','physics_model','model_animation_graph'}]
    return report


def validate(row,payload):
    from io_scene_foundry.managed_blam import Tag
    from io_scene_foundry.managed_blam.model import ModelTag
    report=dict(chain={},runtime_status='NOT_TESTED')
    with Tag(path=row['target_tag'],tag_must_exist=True) as tag:
        base='Struct:device[0]/Struct:object[0]' if row['source_group'] in {'device_machine','device_control'} else 'Struct:object[0]'
        path=tag.tag.SelectField(base+'/Reference:model').Path
        if path is None or str(path.RelativePathWithExtension).replace('\\','/')!=row['target_base']+'.model':raise ValueError('Native object/model link differs')
    with ModelTag(path=row['target_base']+'.model',tag_must_exist=True) as tag:
        fields=[('render_model',tag.reference_render_model),('collision_model',tag.reference_collision_model),('physics_model',tag.reference_physics_model),('model_animation_graph',tag.reference_animation)]
        for kind,field in fields:
            expected=(kind=='render_model' or kind=='collision_model' and bool(payload.get('collision'))
                or kind=='physics_model' and bool(payload.get('physics',{}).get('shapes'))
                or kind=='model_animation_graph' and row['animation_policy']=='SOURCE_DEVICE_JMA_TO_NATIVE_GRAPH')
            if bool(field.Path)!=expected:raise ValueError('Native model dependency presence differs: '+kind)
            if expected:
                path=str(field.Path.RelativePathWithExtension).replace('\\','/')
                if path!=row['target_base']+'.'+kind:raise ValueError('Native model dependency identity differs: '+path)
                with Tag(path=path,tag_must_exist=True) as dependency:
                    item=dict(path=path,status='MANAGEDBLAM_OPENED')
                    if kind=='physics_model':
                        bodies=dependency.tag.SelectField('Block:rigid bodies').Elements
                        if not bodies.Count:raise ValueError('Native physics contains no rigid bodies')
                        item['rigid_bodies']=bodies.Count
                        item['mass']=[float(b.SelectField('mass').Data) for b in bodies]
                        if any(not math.isfinite(m) or m<=0 for m in item['mass']):raise ValueError('Native rigid body mass is not positive')
                    if kind=='model_animation_graph':
                        animations=dependency.tag.SelectField('Block:animations').Elements
                        if not animations.Count:raise ValueError('Native device graph has no animations')
                        item['animations']=[a.SelectField('name').GetStringData() for a in animations]
                    report['chain'][kind]=item
        if tag.get_model_variants()!=[v['name'] for v in payload['variants']]:raise ValueError('Native model variant names differ')
    report['status']='NATIVE_DEPENDENCIES_VERIFIED'
    return report

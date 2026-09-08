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
        for name,item in native.items():target.SetBit(item.FlagName,name in names)
        actual=sorted(name for name,item in native.items() if target.TestBit(item.FlagName))
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
                reg=e.SelectField('regions').AddElement();select(reg,'region name').SetStringData(region['name'])
                for perm in region['permutations']:
                    p=reg.SelectField('permutations').AddElement();select(p,'permutation name').SetStringData(perm['name'])
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
    if (payload.get('physics') or {}).get('shapes'):
        from . import native_physics
        report['physics']=native_physics.author(row)
    return report


def validate(row,payload,animation_authoring=None):
    from io_scene_foundry.managed_blam import Tag
    from io_scene_foundry.managed_blam.model import ModelTag
    from io_scene_foundry.managed_blam.render_model import RenderModelTag
    from io_scene_foundry.h3_import.core import groups
    report=dict(chain={},runtime_status='NOT_TESTED')
    with RenderModelTag(path=row['target_base']+'.render_model',tag_must_exist=True) as render:
        report['render_geometry']=dict(meshes=render.block_meshes.Elements.Count,
            source_triangles=len(payload['render']['triangles']),nodes=render.get_nodes(),
            triangle_validation='Native Tool import log; Reach ManagedBlam has no GameRenderGeometry API')
        if payload['render']['triangles'] and not render.block_meshes.Elements.Count:raise ValueError('Native render meshes are absent')
        if set(render.get_nodes())!={n['name'] for n in payload['render']['nodes']}:raise ValueError('Native skeleton identities differ')
        names=render.get_nodes()
        native_parents={names[n.ElementIndex]:(names[n.SelectField('parent node').Value] if n.SelectField('parent node').Value>=0 else None)
            for n in render.block_nodes.Elements}
        source_nodes=payload['render']['nodes']
        source_parents={n['name']:(source_nodes[n['parent']]['name'] if n['parent']>=0 else None) for n in source_nodes}
        if native_parents!=source_parents:raise ValueError('Native skeleton parent relationships differ')
        report['render_geometry']['parent_relationships']='VERIFIED_BY_NODE_IDENTITY'
        for region,permutation,lod,*rest in groups(payload['render']):
            if lod:raise ValueError('Source LOD selection needs its own native adapter')
            if permutation not in render.get_permutations(region):raise ValueError('Native region/permutation identity differs')
    with Tag(path=row['target_tag'],tag_must_exist=True) as tag:
        base='Struct:device[0]/Struct:object[0]' if row['source_group'] in {'device_machine','device_control'} else 'Struct:object[0]'
        path=tag.tag.SelectField(base+'/Reference:model').Path
        if path is None or str(path.RelativePathWithExtension).replace('\\','/')!=row['target_base']+'.model':raise ValueError('Native object/model link differs')
    with ModelTag(path=row['target_base']+'.model',tag_must_exist=True) as tag:
        fields=[('render_model',tag.reference_render_model),('collision_model',tag.reference_collision_model),('physics_model',tag.reference_physics_model),('model_animation_graph',tag.reference_animation)]
        for kind,field in fields:
            expected=(kind=='render_model' or kind=='collision_model' and bool(payload.get('collision'))
                or kind=='physics_model' and bool((payload.get('physics') or {}).get('shapes'))
                or kind=='model_animation_graph' and row['animation_policy']=='SOURCE_DEVICE_JMA_TO_NATIVE_GRAPH')
            if bool(field.Path)!=expected:raise ValueError('Native model dependency presence differs: '+kind)
            if expected:
                path=str(field.Path.RelativePathWithExtension).replace('\\','/')
                if path!=row['target_base']+'.'+kind:raise ValueError('Native model dependency identity differs: '+path)
                with Tag(path=path,tag_must_exist=True) as dependency:
                    item=dict(path=path,status='MANAGEDBLAM_OPENED')
                    if kind=='physics_model':
                        from . import native_physics
                        item['authoring_readback']=native_physics.validate(dependency.tag,row)
                        bodies=dependency.tag.SelectField('Block:rigid bodies').Elements
                        if not bodies.Count:raise ValueError('Native physics contains no rigid bodies')
                        item['rigid_bodies']=bodies.Count
                        item['mass']=[float(b.SelectField('mass').Data) for b in bodies]
                        if any(not math.isfinite(m) or m<0 for m in item['mass']):raise ValueError('Native rigid body mass is invalid')
                        item['mass_status']='LOOSE_TAG_AUTHORING; zero also observed in unmodified Reach crate and door tags; runtime effective mass not validated'
                    if kind=='model_animation_graph':
                        animations=dependency.tag.SelectField('definitions[0]/animations').Elements
                        if not animations.Count:raise ValueError('Native device graph has no animations')
                        item['animations']=[a.SelectField('name').GetStringData() for a in animations]
                        nodes=dependency.tag.SelectField('definitions[0]/skeleton nodes').Elements
                        item['nodes']=[n.Fields[0].GetStringData() for n in nodes]
                        if set(item['nodes'])!={n['name'] for n in payload['render']['nodes']}:raise ValueError('Native graph skeleton identities differ')
                        item['frame_counts']={a.SelectField('name').GetStringData():int(a.SelectField('shared animation data[0]/frame count').Data)
                            for a in animations}
                        if animation_authoring:
                            if animation_authoring.get('source_clips'):
                                expected={normalized(c['name'].replace(':',' ')):c['native_frames'] for c in animation_authoring['source_clips']}
                            else:
                                raise ValueError('Device source frame-rate/reference-frame receipt is absent')
                            actual={normalized(n.replace(':',' ')):c for n,c in item['frame_counts'].items()}
                            if actual!=expected:raise ValueError('Native animation frame counts or identities differ from source JMA: '+str(dict(source=expected,native=actual)))
                    report['chain'][kind]=item
        if tag.get_model_variants()!=[v['name'] for v in payload['variants']]:raise ValueError('Native model variant names differ')
        from .native_validation import close
        for native,source in zip(tag.block_variants.Elements,payload['variants']):
            regions=native.SelectField('regions').Elements
            if regions.Count!=len(source['regions']):raise ValueError('Native variant region count differs')
            for region,expected in zip(regions,source['regions']):
                if select(region,'region name').GetStringData()!=expected['name']:raise ValueError('Native variant region identity differs')
                permutations=region.SelectField('permutations').Elements
                if permutations.Count!=len(expected['permutations']):raise ValueError('Native variant permutation count differs')
                for permutation,p in zip(permutations,expected['permutations']):
                    if select(permutation,'permutation name').GetStringData()!=p['name']:raise ValueError('Native variant permutation identity differs')
                    close(select(permutation,'probability').Data,p['probability'],'variant permutation probability')
        report['variant_regions_permutations']='SOURCE_IDENTITIES_AND_PROBABILITIES_VERIFIED'
    report['status']='NATIVE_DEPENDENCIES_VERIFIED'
    return report

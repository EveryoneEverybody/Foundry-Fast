"""Complete native material authoring for rmop inputs absent from the node UI."""
import json
from pathlib import Path
from functools import lru_cache
from .paths import digest
from .native_contracts import unexposed_parameter


def complete_tag(material, manifest, report, paths):
    from io_scene_foundry.tools.shader_builder import REACH_SUFFIX_TO_CLASS
    from io_scene_foundry.managed_blam.shader import Parallax
    contract=json.loads(material['h3_native_authoring'])
    staging=json.loads(material['h3_reach_report'])
    cls,_=REACH_SUFFIX_TO_CLASS[material.nwo.shader_type]
    source=manifest['shaders'][material['h3_source_shader']]
    parameter_plan=[]
    target_path=paths.owned_tag(material.nwo.shader_path)
    if target_path.exists():
        # The outer ownership preflight verified the exact previous hash.
        # Reconstruct from nodes, avoiding inheritance from failed partial tags.
        target_path.unlink()
    with cls(path=material.nwo.shader_path) as tag:
        material.nwo.shader_path=tag.write_tag(material,True)
        if contract['target_node']=='foundry_reach.shader':
            parallax=contract['options'].get('parallax','off')
            tag.block_options.Elements[8].SelectField('short').SetStringData(str(Parallax[parallax.upper()].value))
        for row in staging['parameters']:
            param=contract['parameters'][row['name']]
            if row['status']=='runtime_input':continue
            if row['status']=='unmapped':
                decision=unexposed_parameter(param,contract)
                parameter_plan.append(dict(source_parameter=param,**decision))
                for p in decision['target_parameters'].values():
                    write_parameter(tag,material,p)
                continue
            if row['status'] not in {'mapped','snapshot','native_supplemental'}:
                raise ValueError('Native parameter staging failed: '+str(row))
            target=write_parameter(tag,material,param)
            parameter_plan.append(dict(source_parameter=param,target_parameters={param['name']:target},
                resolution_class='NATIVE_TRANSFORM',fidelity_loss=target.get('sampler_fidelity_loss')))
        for i,name in enumerate(source.get('material_names', [])):
            field=tag.tag.SelectField('StringId:material name'+(' '+str(i) if material.nwo.shader_type=='.shader_terrain' else ''))
            if field is None:
                raise ValueError('Target shader lacks source global material authoring field')
            field.SetStringData(name)
        tag.tag_has_changes=True
        tag.tag.Save()
    ensure_template(material.nwo.shader_path,paths,report)
    readback=validate_material(material,contract,parameter_plan,cls)
    report.setdefault('native_material_completion',[]).append(dict(source=material['h3_source_shader'],
        target=material.nwo.shader_path,approximation=contract.get('approximation'),
        supplemental=[r['name'] for r in staging['parameters'] if r['status']=='native_supplemental'],
        parameter_plan=parameter_plan,readback=readback))


def write_parameter(tag,material,param):
    from io_scene_foundry import utils
    name=param['name'];kind=param['type'];value=param.get('value')
    result=dict(param)
    if kind=='bitmap':
        value=next(n for n in material.node_tree.nodes if n.type=='TEX_IMAGE' and n.label==name)
        result['target_bitmap']=str(Path(value.image.nwo.filepath).with_suffix('.bitmap')).replace('\\','/')
    if kind in {'color','argb color'}:
        # H3 snapshots contain source RGB color values. Foundry's public color
        # inputs are linear and its writer applies linear_to_srgb internally.
        value=tuple(utils.srgb_to_linear(v) for v in value[:3])
    if kind in {'int','bool'}:value=int(value)
    element=tag._setup_parameter(value,name,'argb color' if kind in {'color','argb color'} else kind)
    if element is None:raise ValueError('Native source parameter could not be authored: '+name)
    element.SelectField(tag.function_parameters).RemoveAllElements()
    tag._setup_function_parameters(value,element,'color' if kind in {'color','argb color'} else kind)
    if kind=='bitmap':
        sampler=param.get('sampler',{})
        schema=sampler_schema()
        result['target_sampler']={}
        for field,key in [('bitmap address mode','address_x'),('bitmap address mode x','address_x'),
            ('bitmap address mode y','address_y'),('bitmap filter mode','filter')]:
            if key in sampler:
                names=schema['filter' if key=='filter' else 'address']
                name=sampler[key].casefold()
                # Reach retires H3's odd anisotropy levels. Select the next
                # supported level; retain the source request in the receipt.
                name={'anisotropic (1)':'anisotropic (2) expensive',
                    'anisotropic (3) expensive':'anisotropic (4) expensive'}.get(name,name)
                if name!=sampler[key].casefold():
                    result['sampler_fidelity_loss']='Reach uses the next supported anisotropy level: '+sampler[key]+' -> '+name+'; texture identity, addressing and UV transform are unchanged'
                if name not in names:raise ValueError('Unmapped Reach sampler '+field+'='+sampler[key])
                element.SelectField(field).Data=names[name]
                result['target_sampler'][field]=names[name]
        # Gen3 per-field override gates: filter, combined address, X, Y.
        # Values come from the installed Reach RMO enum, never H3 ordinals.
        element.SelectField('bitmap flags').Data=15
    return result


@lru_cache(maxsize=1)
def sampler_schema():
    from io_scene_foundry.managed_blam.render_method_option import RenderMethodOptionTag
    with RenderMethodOptionTag(path='shaders/shader_options/albedo_default.render_method_option',tag_must_exist=True) as tag:
        p=tag.block_parameters.Elements[0]
        return {kind:{i.EnumName.casefold():i.EnumIndex for i in p.SelectField(field).Items}
            for kind,field in [('filter','default filter mode'),('address','default address mode')]}


def validate_material(material,contract,parameters,cls):
    from .native_validation import close
    from io_scene_foundry.managed_blam.render_method_definition import RenderMethodDefinitionTag
    with cls(path=material.nwo.shader_path,tag_must_exist=True) as tag:
        with RenderMethodDefinitionTag(path=tag.definition.Path,tag_must_exist=True) as definition:
            options={}
            for i,c in enumerate(definition.block_categories.Elements):
                options[c.Fields[0].GetStringData()]=c.Fields[1].Elements[tag._option_value_from_index(i)].Fields[0].GetStringData()
        for name,expected in contract['options'].items():
            if name in {'distortion','soft_fade','misc_attr_animation'} and expected=='off':continue
            if name=='misc' and expected=='first_person_never' and options.get(name)=='default':continue
            if options.get(name)!=expected:raise ValueError('Native shader option readback differs: '+name)
        native={p.SelectField('parameter name').GetStringData():p for p in tag.block_parameters.Elements}
        count=0
        for decision in parameters:
            for name,p in decision['target_parameters'].items():
                if name not in native:raise ValueError('Native shader parameter missing: '+name)
                element=native[name]
                functions={a.SelectField('type').Value:a.SelectField(tag.animated_function).Value
                    for a in element.SelectField(tag.function_parameters).Elements}
                if p['type']=='bitmap':
                    path=element.SelectField('bitmap').Path
                    if path is None or str(path.RelativePathWithExtension).replace('\\','/')!=p['target_bitmap']:
                        raise ValueError('Native bitmap binding differs: '+name)
                    for field,expected in p['target_sampler'].items():
                        close(element.SelectField(field).Data,expected,name+' '+field)
                    close(element.SelectField('bitmap flags').Data,15,name+' sampler override gates')
                    for channel,expected in zip((3,4,5,6),p['transform']):
                        actual=functions[channel].ClampRangeMin if channel in functions else (1 if channel in (3,4) else 0)
                        close(actual,expected,name+' source UV transform')
                elif p['type'] in {'color','argb color'}:
                    if 1 not in functions:raise ValueError('Native color function missing: '+name)
                    color=functions[1].GetColor(0)
                    if color.ColorMode==1:color=color.ToRgb()
                    close([color.Red,color.Green,color.Blue],p['value'][:3],name+' source color',tolerance=1/255+.00001)
                elif p['type'] in {'real','int','bool'}:
                    value=functions[0].ClampRangeMin if 0 in functions else element.SelectField('real' if p['type']=='real' else 'int\\bool').Data
                    close(value,p['value'],name+' source value')
                count+=1
        return dict(status='VERIFIED',options=options,source_parameters_read_back=count)


def ensure_template(shader_path, paths, report):
    """Generate missing native code with an owned definition/template namespace.

    The definition is unchanged Reach shader infrastructure. ManagedBlam must
    derive an in-namespace template identity before Tool may run.
    """
    from io_scene_foundry.managed_blam.shader import ShaderTag
    from io_scene_foundry import utils
    field='Struct:render_method[0]/Block:postprocess[0]/Reference:shader template'
    with ShaderTag(path=shader_path,tag_must_exist=True) as tag:
        template=tag.tag.SelectField(field)
        if template is None or template.Path is None:
            raise ValueError('Native shader has no template identity: '+shader_path)
        if Path(template.Path.Filename).is_file():
            return
        source=Path(tag.definition.Path.Filename)
        owned=paths.destination('tags',source.name,infrastructure=True)
        if source!=owned:
            if owned.exists() and digest(owned)!=digest(source):
                raise ValueError('Owned Reach shader definition differs from source infrastructure')
            if not owned.exists():
                owned.parent.mkdir(parents=True,exist_ok=True)
                with owned.open('xb') as stream:
                    stream.write(source.read_bytes())
            tag.definition.Path=tag._TagPath_from_string(str(owned.relative_to(paths.roots['tags'])))
            tag.tag_has_changes=True
            tag.tag.Save()
        source_hash=digest(owned)
    with ShaderTag(path=shader_path,tag_must_exist=True) as tag:
        template=tag.tag.SelectField(field).Path
        target=Path(template.Filename).resolve()
        if not target.is_relative_to(paths.destination('tags',infrastructure=True)):
            raise ValueError('Reach did not derive an owned template identity: '+str(template.RelativePathWithExtension))
        definition=str(tag.definition.Path.RelativePath)
        name=Path(template.RelativePath).name
        report.setdefault('native_template_authoring',[]).append(dict(shader=shader_path,
            source_definition=str(source.relative_to(paths.roots['tags'])).replace('\\','/'),
            source_definition_sha256=digest(source),
            definition=definition,definition_sha256=source_hash,template=str(template.RelativePathWithExtension),
            strategy='Unchanged Reach definition in owned namespace; Reach Tool compiles native shader code'))
    if not target.is_file():
        utils.run_tool(['generate-specified-template','win',definition,name])
    if not target.is_file():
        raise ValueError('Reach Tool did not produce the owned shader template: '+str(target))

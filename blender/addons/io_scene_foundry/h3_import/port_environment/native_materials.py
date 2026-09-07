"""Complete native material authoring for rmop inputs absent from the node UI."""
import json
from pathlib import Path
from .paths import digest


def complete_tag(material, manifest, report, paths):
    from io_scene_foundry.tools.shader_builder import REACH_SUFFIX_TO_CLASS
    from io_scene_foundry.managed_blam.shader import Parallax
    contract=json.loads(material['h3_native_authoring'])
    staging=json.loads(material['h3_reach_report'])
    cls,_=REACH_SUFFIX_TO_CLASS[material.nwo.shader_type]
    source=manifest['shaders'][material['h3_source_shader']]
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
            if row['status']!='native_supplemental':continue
            param=row['source_parameter'];kind=param['type'];name=param['name']
            value=param.get('value')
            if kind=='bitmap':
                value=next(n for n in material.node_tree.nodes if n.get('h3_native_supplemental_parameter')==name)
            tag_kind='argb color' if kind in {'color','argb color'} else kind
            function_kind='color' if kind in {'color','argb color'} else kind
            if function_kind == 'color':
                # The normalized H3 recipe is RGBA; Foundry's function editor
                # accepts RGB, with alpha retained in the source recipe.
                value=tuple(value[:3])
            element=tag._setup_parameter(value,name,tag_kind)
            if element is None:
                raise ValueError('Native supplemental parameter could not be authored: '+name)
            tag._setup_function_parameters(value,element,function_kind)
        for i,name in enumerate(source.get('material_names', [])):
            field=tag.tag.SelectField('StringId:material name'+(' '+str(i) if material.nwo.shader_type=='.shader_terrain' else ''))
            if field is None:
                raise ValueError('Target shader lacks source global material authoring field')
            field.SetStringData(name)
        tag.tag_has_changes=True
        tag.tag.Save()
    ensure_template(material.nwo.shader_path,paths,report)
    report.setdefault('native_material_completion',[]).append(dict(source=material['h3_source_shader'],
        target=material.nwo.shader_path,approximation=contract.get('approximation'),
        supplemental=[r['name'] for r in staging['parameters'] if r['status']=='native_supplemental']))


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
            definition=definition,definition_sha256=source_hash,template=str(template.RelativePathWithExtension),
            strategy='Unchanged Reach definition in owned namespace; Reach Tool compiles native shader code'))
    if not target.is_file():
        utils.run_tool(['generate-specified-template','win',definition,name])
    if not target.is_file():
        raise ValueError('Reach Tool did not produce the owned shader template: '+str(target))

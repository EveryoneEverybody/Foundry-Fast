"""Reach writer boundary, including native compatibility lowering of semantic plans."""
import json
import math
from hashlib import sha256
from .material_translation import (ReachAuthoringPlan, TRANSLATED, TWO, SINGLE,
                                   canonical_json, roughness_to_compatibility_power)


def writer_issues(plan, declarations=None):
    """Check a plan against selected native RMOP declarations, when available.

    Missing declarations never authorize the hidden compatibility lane. Node
    sockets are not declarations: callers must read the selected native RMOPs.
    """
    contract = plan.to_dict() if isinstance(plan, ReachAuthoringPlan) else plan
    issues = []
    if contract.get('format') != 'foundry.h3-reach-material-plan' or contract.get('version') != 1:
        return ['UNRESOLVED_WRITER_CONTRACT: expected semantic plan v1']
    if contract.get('target_node') != 'foundry_reach.shader' or contract.get('destination_group') != 'rmsh':
        issues.append('UNRESOLVED_WRITER_CONTRACT: ordinary Reach shader target required')
    if contract.get('translation_status') != TRANSLATED:
        blockers = [d for d in contract.get('diagnostics', []) if d.get('still_blocking', True)]
        issues.append('UNRESOLVED_REQUIRES_RULE: ' + json.dumps(blockers, sort_keys=True))
    if contract.get('rule_id') in {SINGLE, TWO}:
        if contract.get('options', {}).get('material_model') != 'two_lobe_phong':
            issues.append('UNRESOLVED_WRITER_CONTRACT: explicit two_lobe_phong target missing')
        if contract.get('parameters', {}).get('specular_color_by_angle', {}).get('type') != 'angle_color':
            issues.append('UNRESOLVED_WRITER_CONTRACT: complete angle-color function missing')
        else:
            angle = contract['parameters']['specular_color_by_angle'].get('value', {})
            colors = [angle.get(k) for k in ('color0_normal', 'color1_glancing')]
            if (not all(isinstance(c, (list, tuple)) and len(c) == 4 and all(_finite(v) for v in c) for c in colors)
                    or not _finite(angle.get('exponent'))):
                issues.append('UNRESOLVED_WRITER_CONTRACT: complete angle-color endpoints/exponent required')
    if contract.get('rule_id') == TWO and 'glancing_roughness' not in contract.get('compatibility_inputs', {}):
        issues.append('UNRESOLVED_WRITER_CONTRACT: glancing_roughness missing from compatibility inputs')
    for name, parameter in contract.get('compatibility_inputs', {}).items():
        if name == 'glancing_roughness':
            value = parameter.get('value')
            if (contract.get('options', {}).get('material_model') != 'two_lobe_phong'
                    or parameter.get('type') != 'real' or not _finite(value) or not 0 <= value <= 1
                    or parameter.get('has_functions') or parameter.get('functions') or parameter.get('extern')):
                issues.append('UNRESOLVED_WRITER_COMPATIBILITY: glancing_roughness requires static finite [0,1] roughness and Reach two_lobe_phong')
            elif declarations is None or 'glancing_specular_power' not in declarations:
                issues.append('UNRESOLVED_WRITER_RMOP: glancing_roughness requires selected native RMOP declaration of glancing_specular_power')
            if 'glancing_specular_power' in contract.get('parameters', {}):
                issues.append('UNRESOLVED_WRITER_COMPATIBILITY: glancing_specular_power must be derived from semantic glancing_roughness')
            continue
        if parameter.get('type') == 'extern' and parameter.get('provider') == 'Reach renderer':
            continue
        issues.append('UNRESOLVED_WRITER_COMPATIBILITY: ' + name +
                      ' retained in plan; native save/postprocess consumption is not verified')
    if declarations is not None:
        for name in contract.get('parameters', {}):
            if name not in declarations:
                issues.append('UNRESOLVED_WRITER_PARAMETER: selected Reach RMOP does not declare ' + name)
    return issues


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def require_writable(plan, declarations=None):
    issues = writer_issues(plan, declarations)
    if issues:
        raise ValueError('; '.join(issues))
    return plan.to_dict() if isinstance(plan, ReachAuthoringPlan) else plan


def native_parameters(plan, declarations):
    """Lower proven compatibility state without mutating the semantic plan.

    Native HREK save/reopen verified both this hidden field and the complete
    TwoColor/Exponent function. Tool/Faux is not needed for their persistence.
    """
    contract = require_writable(plan, declarations)
    parameters = dict(contract['parameters'])
    glancing = contract.get('compatibility_inputs', {}).get('glancing_roughness')
    if glancing is not None:
        parameters['glancing_specular_power'] = dict(name='glancing_specular_power', type='real',
            value=roughness_to_compatibility_power(glancing['value']), origin='REACH_DERIVED',
            source_fields=['glancing_roughness'], semantic_value=glancing['value'],
            compatibility_rule='reach.glancing_roughness_to_glancing_specular_power.v1', has_functions=False)
    return parameters


def require_source(plan, record):
    contract = plan.payload if isinstance(plan, ReachAuthoringPlan) else plan
    digest = sha256(canonical_json(record).encode()).hexdigest()
    if contract.get('source_shader') != record.get('source') or contract.get('source_record_sha256') != digest:
        raise ValueError('UNRESOLVED_WRITER_SOURCE: plan belongs to a different or changed H3 source record')


def write_angle_color(tag, parameter, color_factory):
    """Write the full native two-color exponent function, never a RGB snapshot.

    API and endpoint order: ShaderTag.get_model_material_spec; FunctionEditor
    enums/accessors in managed_blam/Tags.py. Color values are in tag RGB space.
    """
    angle = parameter['value']
    element = tag._setup_parameter(None, parameter['name'], 'argb color')
    block = element.SelectField(tag.function_parameters)
    block.RemoveAllElements()
    function = block.AddElement()
    tag._set_animated_parameter_type(function, 1)  # AnimatedParameterType.COLOR
    editor = function.SelectField(tag.animated_function).Value
    editor.MasterType = tag._FunctionEditorMasterType(3)  # Exponent
    editor.ColorGraphType = tag._FunctionEditorColorGraphType(2)  # TwoColor
    editor.SetColor(0, color_factory(angle['color0_normal']))
    editor.SetColor(1, color_factory(angle['color1_glancing']))
    editor.SetExponent(0, angle['exponent'])
    editor.SetAmplitudeMin(0, 0.0)
    editor.SetAmplitudeMax(0, 1.0)
    return element


def verify_angle_color(tag, parameter, element):
    from .port_environment.native_validation import close
    functions = element.SelectField(tag.function_parameters).Elements
    color = next((f for f in functions if f.SelectField('type').Value == 1), None)
    if color is None:
        raise ValueError('Native angle-color function missing')
    editor = color.SelectField(tag.animated_function).Value
    def enum_int(value):
        return int(getattr(value, 'value__', getattr(value, 'value', value)))
    if enum_int(editor.MasterType) != 3 or enum_int(editor.ColorGraphType) != 2:
        raise ValueError('Native angle-color function representation differs')
    for i, name in enumerate(('color0_normal', 'color1_glancing')):
        c = editor.GetColor(i)
        if c.ColorMode == 1:
            c = c.ToRgb()
        close([c.Red, c.Green, c.Blue, c.Alpha], parameter['value'][name], name, tolerance=1/255+.00001)
    close(editor.GetExponent(0), parameter['value']['exponent'], 'angle-color exponent')
    close(editor.GetAmplitudeMin(0), 0, 'angle-color minimum')
    close(editor.GetAmplitudeMax(0), 1, 'angle-color maximum')


def apply_plan(tag, material, contract):
    """Called by the normal ShaderTag writer as well as native completion.

    Validate every destination identity against selected Reach RMOPs before
    authoring. Hidden compatibility values are lowered only at this boundary.
    """
    contract = contract.to_dict() if isinstance(contract, ReachAuthoringPlan) else contract
    from .reach_builder import read_destination_aliases
    from .port_environment.native_materials import write_parameter
    from ..managed_blam.render_method_definition import RenderMethodDefinitionTag
    from .. import utils
    with RenderMethodDefinitionTag(path=tag.definition.Path, tag_must_exist=True) as definition:
        categories = {c.Fields[0].GetStringData(): c for c in definition.block_categories.Elements}
        missing = set(categories) - set(contract['options'])
        if missing:
            raise ValueError('UNRESOLVED_WRITER_CATEGORY: plan has no selection for '+', '.join(sorted(missing)))
        selections = []
        for name, option in contract['options'].items():
            if name not in categories:
                raise ValueError('UNRESOLVED_WRITER_CATEGORY: ' + name)
            category = categories[name]
            choices = [o.Fields[0].GetStringData() for o in category.Fields[1].Elements]
            if option not in choices:
                raise ValueError('UNRESOLVED_WRITER_OPTION: ' + name + '=' + option)
            selections.append((category.ElementIndex, choices.index(option)))
    declarations, notes = read_destination_aliases(contract['options'], {}, definition_path=tag.definition.Path)
    if notes:
        raise ValueError('UNRESOLVED_WRITER_RMOP: ' + '; '.join(notes))
    parameters = native_parameters(contract, declarations)
    for index, option in selections:
        tag.block_options.Elements[index].SelectField('short').Data = option
    tag.reference.Path = None  # All inherited H3 values were resolved upstream.
    # Remove previous authored/default controls. Only the semantic plan is
    # authoritative; the generic node writer never handles this material.
    tag.block_parameters.RemoveAllElements()
    receipt = []
    for parameter in parameters.values():
        if parameter['type'] == 'angle_color':
            element = write_angle_color(tag, parameter, lambda c: tag._GameColor_from_ARGB(
                c[3], *(utils.srgb_to_linear(v) for v in c[:3])))
            verify_angle_color(tag, parameter, element)
            target = parameter
        else:
            target = write_parameter(tag, material, parameter)
        receipt.append(dict(target_parameters={parameter['name']: target}))
    tag.tag_has_changes = True
    return receipt

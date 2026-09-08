"""Pure lowering of accepted source semantics into Foundry authoring contracts."""
from copy import deepcopy


def material(row):
    result = dict(target_node='foundry_reach.shader',
        options={c['category']:c['option'] for c in row['source_categories']},
        parameters={p['name']:deepcopy(p) for p in row['source_parameters']})
    for decision in row.get('semantic_authoring', []):
        if decision['still_blocking']:
            raise ValueError('Blocking material decision')
        target = decision['target_authoring_plan']
        if 'target_node' in target:
            result.update(target_node=target['target_node'], options=target['options'],
                parameters=deepcopy(target.get('parameter_bindings', target.get('parameters', {}))))
    for name, parameter in result['parameters'].items():
        parameter.setdefault('name', name)
    model = result['options'].get('material_model')
    if model in {'single_lobe_phong','glass'}:
        result['options']['material_model']='two_lobe_phong'
        result['approximation']=dict(source=model,target='two_lobe_phong',
            evidence='Reach ShaderGlassTag requires TWO_LOBE_PHONG; ordinary Reach ShaderTag supports the same model with alpha_blend',
            preserved='Source base/normal/specular textures, authored alpha blend/cutout and environment option',
            fidelity_loss='Reach two-lobe response replaces the H3 reflection model; exact BRDF parity is not claimed')
    return result


def collision_face(flags):
    if flags & ~15:
        raise ValueError(f'Unmapped collision flags: {flags}')
    if flags & 8:
        raise ValueError('Breakable collision requires proven unified render geometry')
    return dict(face_mode='sphere_collision_only' if flags & 2 else 'collision_only',
                two_sided=bool(flags & 1), ladder=bool(flags & 4))


def unexposed_parameter(parameter, contract):
    """Bounded target BRDF differences, never a generic missing-input fallback."""
    name=parameter['name'];value=parameter.get('value')
    if name=='bump_detail_coefficient' and value==1:
        return dict(resolution_class='NATIVE_TRANSFORM',target_parameters={},fidelity_loss=None,
            evidence='Reach templated/bump_mapping.hlsl_include calc_bumpmap_detail_ps adds detail.xy with unit coefficient')
    if name=='order3_area_specular' and value is False:
        return dict(resolution_class='NATIVE_TRANSFORM',target_parameters={},fidelity_loss=None,
            evidence='Source optional third-order area-specular path is disabled; Reach uses its native area-light BRDF')
    if name=='analytical_anti_shadow_control':
        return dict(resolution_class='OPTIONAL_MVP_OMISSION',target_parameters={},
            evidence='Reach material_two_lobe_phong_option lacks the H3 analytical anti-shadow control; native light definitions and source specular contributions remain authored',
            fidelity_loss='H3 analytical specular anti-shadow adjustment is replaced by Reach native shadow response')
    if name=='specular_tint' and contract['options'].get('material_model')=='two_lobe_phong':
        return dict(resolution_class='NATIVE_TRANSFORM',
            target_parameters={k:dict(parameter,name=k) for k in ('normal_specular_tint','glancing_specular_tint')},
            evidence='Reach material_two_lobe_phong_option exposes normal and glancing tint colors; one source tint applies to both',
            fidelity_loss='The accepted Reach two-lobe BRDF replaces the source single-lobe response')
    if name in {'fresnel_coefficient','fresnel_curve_bias'} and contract.get('approximation',{}).get('source')=='glass':
        return dict(resolution_class='OPTIONAL_MVP_OMISSION',target_parameters={},
            evidence='Accepted glass to Reach two-lobe BRDF approximation retains authored alpha, environment map and specular tint',
            fidelity_loss='H3 glass-specific Fresnel curve control is replaced by Reach native angular reflection; alpha and collision are unaffected')
    raise ValueError('Native material has an unclassified unexposed source parameter: '+name)


def unified_mesh(render, proof):
    if not proof['all_collision_rings_covered'] or not proof['all_render_faces_covered']:
        raise ValueError('Incomplete unified breakable proof')
    result = deepcopy(render)
    kept = proof['retained_render_triangles']
    result['triangles'] = [deepcopy(render['triangles'][i]) for i in kept]
    # Keep corner attributes at original split vertices, snap only positions to
    # the exact proven collision/render equivalence classes. Tool welds topology.
    for i,v in enumerate(result['vertices']):
        position = proof['render_vertex_position_ids'][i]
        if position>=0:
            v['position'] = proof['unified_position_table'][position]
    result.update(face_mode='breakable', mesh_type='_connected_geometry_mesh_type_default', role='unified_breakable')
    return result

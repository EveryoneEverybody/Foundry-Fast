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


def unified_mesh(render, proof):
    if not proof['all_collision_rings_covered'] or not proof['all_render_faces_covered']:
        raise ValueError('Incomplete unified breakable proof')
    result = deepcopy(render)
    kept = proof['retained_render_triangles']
    result['triangles'] = [deepcopy(render['triangles'][i]) for i in kept]
    # Keep corner attributes at original split vertices, snap only positions to
    # the exact proven collision/render equivalence classes. Tool welds topology.
    for i,v in enumerate(result['vertices']):
        v['position'] = proof['unified_position_table'][proof['render_vertex_position_ids'][i]]
    result.update(face_mode='breakable', mesh_type='_connected_geometry_mesh_type_default', role='unified_breakable')
    return result

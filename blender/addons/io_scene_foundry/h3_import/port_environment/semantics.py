"""Pure source-contract resolution. This module cannot write Reach data/tags.

Diagnostics are immutable observations, not a list to prune. Every observation
receives a stable identity and a rule result, including unrecognized observations.
All target constructs below are writer contracts, not claims of native acceptance.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import struct

from .authoring import number

CLASSES = ('NATIVE_DIRECT', 'NATIVE_TRANSFORM', 'NATIVE_REBUILD', 'STATICIZED_MVP',
           'OPTIONAL_MVP_OMISSION', 'RUNTIME_LATER', 'BLOCKING_UNKNOWN')
CATALOG_PATH = Path(__file__).with_name('semantic_catalog.json')
CATALOG = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
RULES = {r['id']: r for r in CATALOG['rules']}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def record_id(record):
    # Diagnostic prose/status and extraction order are not source identity.
    identity = {k: deepcopy(v) for k, v in record.items() if k not in {'reason', 'status', 'count'}}
    for name in ('affected', 'affected_instances'):
        if name in identity:
            identity[name] = sorted(identity[name], key=canonical)
    return 'h3-contract-' + sha(identity)


def decision(rule, classification, target, *, loss=None, confidence='HIGH', reason=None):
    if rule not in RULES or classification not in CLASSES:
        raise ValueError('Unknown semantic resolution rule/class')
    return dict(semantic_rule_id=rule, resolution_class=classification,
                evidence=RULES[rule]['evidence'], confidence=confidence,
                target_authoring_plan=target, fidelity_loss=loss or [],
                still_blocking=classification == 'BLOCKING_UNKNOWN', reason=reason)


def unknown(rule, reason, source=None):
    return decision(rule, 'BLOCKING_UNKNOWN', dict(source_evidence=source, missing_fact=reason),
                    reason=reason, confidence='INSUFFICIENT_FOR_CONVERSION')


def options(shader):
    pairs = [(p['category'], p['option']) for p in shader.get('categories', [])]
    if len(dict(pairs)) != len(pairs):
        raise ValueError('Duplicate source shader category')
    return dict(pairs)


def finite(value):
    if isinstance(value, list):
        return bool(value) and all(finite(v) for v in value)
    return type(value) in (int, float) and math.isfinite(value)


def function_header(function):
    data = bytes.fromhex(function['function_hex'])
    if len(data) < 32 or data[0] > 10 or data[1] & ~63 or data[2] > 4:
        raise ValueError('Unrecognized function header')
    return dict(type=data[0], flags=data[1], color_graph=data[2],
                lower=struct.unpack_from('<f', data, 4)[0] if data[2] == 0 else None,
                bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def parameter_plan(parameter, authored, categories, *, baked_emission_preserved=False, required_bake_emission=False):
    name = parameter['name']
    extern = parameter.get('extern')
    if extern:
        if extern in {'dynamic environment map 1', 'dynamic environment map 2'}:
            if categories.get('environment_mapping', categories.get('environment_map')) != 'dynamic':
                return unknown('material.engine_extern', 'Dynamic cube extern without matching native environment option', parameter)
            return decision('material.engine_extern', 'NATIVE_REBUILD', dict(source_parameter=parameter,
                target='Reach dynamic environment mapping; target reflection resources rebuilt from this environment',
                runtime_resource_copy=False, runtime_provider='Reach renderer'))
        if extern in {'cook torrance cc0236', 'cook torrance dd0236', 'cook torrance c78d78'}:
            return decision('material.engine_extern', 'NATIVE_TRANSFORM', dict(source_parameter=parameter,
                target='Native Reach material model owns its BRDF lookup extern', runtime_resource_copy=False),
                loss=['Reach BRDF implementation replaces the H3 BRDF implementation'])
        if extern == 'tree animation timer' and name == 'g_tree_animation_coeff':
            return decision('material.engine_extern', 'STATICIZED_MVP', dict(source_parameter=parameter,
                target_value=0.0, target_animation_amplitude_horizontal=0.0,
                canonical_state='Authored undeformed foliage mesh; disable displacement amplitude and timer',
                target='Freeze wind only; retain base_map and alpha_test_map'), loss=['Foliage wind animation and its phase displacement'])
        return unknown('material.engine_extern', 'No verified Reach provider for this active extern', parameter)
    value = parameter.get('transform') if parameter['type'] == 'bitmap' else parameter.get('value')
    if not finite(value):
        return unknown('material.parameters', 'Canonical source parameter value is absent/nonfinite', parameter)
    functions = authored.get('functions', [])
    if parameter.get('has_functions') and not functions:
        return unknown('material.parameters', 'Resolved snapshot has functions but original function bytes are absent', parameter)
    if (name == 'back_light' and categories == dict(albedo='default',alpha_test='simple',material_model='default')
        and all(function_header(f)['type'] == 1 and not function_header(f)['flags'] & 1 for f in functions)):
        return decision('foliage.native_cutout', 'OPTIONAL_MVP_OMISSION', dict(source_parameter=parameter,
            source_functions=functions, target_binding=None,
            evidence='Stock H3 foliage_fx declares back_light but its static_common lighting does not read it; Reach has no matching color input',
            retained_value=value, target='Native Reach foliage flat diffuse lighting; keep source recipe archived'),
            confidence='MEDIUM', loss=['Authored back_light recipe retained without a native Reach color socket; diffuse lighting uses Reach foliage'])
    results = []
    for function in functions:
        header = function_header(function)
        source = dict(parameter=name, function=function, decoded_header=header,
                      source_default=authored, resolved_parameter=parameter)
        if header['type'] == 1 and not header['flags'] & 1:
            results.append(decision('material.constant', 'NATIVE_DIRECT', dict(source=source,
                target_value=value, convention='Authored constant channel; independent of runtime input/time')))
            continue
        # Named providers have no canonical engine state in this static compiler.
        if function.get('input') or function.get('range'):
            results.append(unknown('material.canonical_animation', 'Named runtime function provider is unresolved', source))
            continue
        channel = function.get('channel')
        alpha = categories.get('alpha_test', 'none')
        safe_uv = (parameter['type'] == 'bitmap' and channel in {'translation x', 'translation y'}
                   and alpha in {'none', 'off'} and name not in {'alpha_test_map', 'opacity_map', 'visibility_map'})
        safe_emission = (name == 'self_illum_intensity' and channel == 'value'
                         and baked_emission_preserved and type(value) in (int, float)
                         and (value > 0 or value == 0 and not required_bake_emission))
        if (safe_uv or safe_emission) and header['type'] in {2, 3, 8}:
            results.append(decision('material.canonical_animation', 'STATICIZED_MVP', dict(source=source,
                target_value=value, convention='Pinned H3 decoder: source time 0, unnamed input 0',
                safety=dict(collision_unchanged=True, topology_unchanged=True, alpha_test_unchanged=True,
                    blend_mode_unchanged=True, static_bake_inputs_preserved=baked_emission_preserved),
                behavior='Freeze cosmetic UV motion' if safe_uv else 'Freeze visible emission modulation; preserve authored bake power/color'),
                loss=['Runtime UV motion' if safe_uv else 'Runtime emissive pulse/flicker']))
        else:
            results.append(unknown('material.canonical_animation',
                'Not a proven cosmetic UV/emission channel; opacity, visibility, cutout and unknown curves remain blocking', source))
    classification = max((r['resolution_class'] for r in results), key=CLASSES.index, default='NATIVE_DIRECT')
    return decision('material.parameters', classification, dict(parameter=name, target_value=value, channels=results),
                    loss=[v for r in results for v in r['fidelity_loss']])


def material_functions(shader, affected, baked_emission_preserved, required_bake_emission=False):
    authored = {p['name']: p for p in shader.get('authored_parameters', [])}
    parameters = {p['name']: p for p in shader.get('parameters', [])}
    rows = [parameter_plan(parameters[name], authored.get(name, {}), options(shader),
                           baked_emission_preserved=baked_emission_preserved,
                           required_bake_emission=required_bake_emission) for name in affected]
    classification = max((r['resolution_class'] for r in rows), key=CLASSES.index, default='NATIVE_DIRECT')
    return decision('material.parameters', classification, dict(parameters=rows,
        canonical_state='Source time/input 0, never wall-clock time', source_evaluation=shader.get('evaluation')),
        loss=sorted({loss for r in rows for loss in r['fidelity_loss']}))


def render_part(part, shader):
    c = options(shader)
    kind, flags = part['part type'], number(part['part flags'])
    blend, alpha = c.get('blend_mode', 'opaque'), c.get('alpha_test', 'none')
    if kind not in {2, 3, 4, 5} or flags & ~2 or blend not in {'opaque', 'alpha_blend', 'additive'} or alpha not in {'none', 'off', 'simple'}:
        return unknown('surface.render_pass', 'Unrecognized draw, blend, cutout or lightmapper category', dict(part=part, shader_categories=c))
    target = dict(source_part=part, source_shader_categories=c,
        draw_category={2:'opaque_shadow_casting',3:'opaque_nonshadowing',4:'transparent',5:'lightmap_only'}[kind],
        alpha_test='simple' if alpha == 'simple' else 'none', blend_mode=blend,
        face_mode='lightmap_only' if kind == 5 else 'normal', no_shadow=kind == 3,
        face_transparent=kind == 4, lightmap_ignore=bool(flags & 2),
        collision_policy='Independent source collision geometry; render part type never invents collision',
        target_shader_group='foundry_reach.shader')
    return decision('surface.render_pass', 'NATIVE_TRANSFORM', target)


def terrain_plan(shader):
    c = options(shader)
    p = {x['name']: deepcopy(x) for x in shader['parameters']}
    if c.get('blending') not in {'morph', 'dynamic_morph'} or c.get('environment_map') not in {'none', 'per_pixel', 'dynamic'}:
        return unknown('terrain.native_layers', 'Unsupported terrain blend/environment option', c)
    layers, target_options = [], dict(blending=c['blending'], environment_map=c['environment_map'])
    names = shader.get('material_names', [])
    for i in range(4):
        choice = c.get(f'material_{i}')
        short = (choice or '').split('_(')[0]
        if short not in {'diffuse_only', 'diffuse_plus_specular', 'off'}:
            return unknown('terrain.native_layers', 'Unknown terrain layer semantic', dict(layer=i, choice=choice))
        target_options[f'material_{i}'] = choice
        if short == 'off':
            continue
        if f'base_map_m_{i}' not in p or not p[f'base_map_m_{i}'].get('bitmap'):
            return unknown('terrain.native_layers', 'Active terrain layer lacks source base pixels', i)
        layers.append(dict(source_layer=i, blend_channel='RGBA'[i], option=choice,
            global_material=names[i] if i < len(names) else '',
            parameters={k:v for k,v in p.items() if k.endswith(f'_m_{i}')},
            detail_bump_enabled=c.get('material_3') == 'off'))
    if not layers or not p.get('blend_map', {}).get('bitmap'):
        return unknown('terrain.native_layers', 'Terrain requires active layers and blend map', c)
    if c['blending'] == 'dynamic_morph' and any(n not in p for n in ('dynamic_material', 'transition_threshold', 'transition_sharpness')):
        return unknown('terrain.native_layers', 'Dynamic morph controls are incomplete', p)
    return decision('terrain.native_layers', 'NATIVE_TRANSFORM', dict(
        target_tag_group='shader_terrain', target_node='foundry_reach.shader_terrain',
        target_writer='ShaderTerrainTag.write_tag', options=target_options,
        layers=layers, active_layers=[r['source_layer'] for r in layers],
        blend_map=p['blend_map'], blend_sampling='linear data; RGBA in source order',
        normalized_recipe=dict(weights='Active RGBA channels divided by their sum',
            source_zero_sum='Undefined division in stock H3 terrain shader; existing inspection preview guards with 1e-8',
            native_zero_sum='Stock Reach D3D11 terrain adds 1e-8 to sampled blend channels before normalization',
            dynamic_morph='saturate((A - transition_threshold) * transition_sharpness), lerp RGB0 toward dynamic_material before normalization'
                          if c['blending'] == 'dynamic_morph' else None),
        parameters=p, material_names=names, single_material=shader.get('source_description', {}).get('single_material'),
        texture_transforms='Preserve each sampler XY scale and ZW translation via Texture Tiling',
        native_writes=False), loss=['Reach terrain lighting response may differ; H3 layers/textures/weights are retained',
            'Reach D3D11 applies its native 1e-8 blend-channel guard at source zero-weight texels'])


def foliage_plan(shader):
    c = options(shader); p = {x['name']: deepcopy(x) for x in shader['parameters']}
    if c != dict(albedo='default', alpha_test='simple', material_model='default'):
        return unknown('foliage.native_cutout', 'Unverified foliage option combination', c)
    if not p.get('alpha_test_map', {}).get('bitmap') or not p.get('base_map', {}).get('bitmap'):
        return unknown('foliage.native_cutout', 'Required foliage base/cutout texture is absent', p)
    bindings = {name:value for name,value in p.items() if name not in {'back_light','g_tree_animation_coeff'}}
    bindings['animation_amplitude_horizontal'] = dict(type='real', value=0.0,
        source=p.get('animation_amplitude_horizontal'), convention='Authored rest mesh; wind staticization')
    return decision('foliage.native_cutout', 'NATIVE_TRANSFORM', dict(
        target_tag_group='shader_foliage', target_node='foundry_reach.shader_foliage',
        target_writer='ShaderFoliageTag.write_tag', options=dict(albedo='default', alpha_test='from_texture', material_model='flat'),
        parameter_bindings=bindings, source_parameters=p, alpha_test=dict(texture=p['alpha_test_map'], channel='alpha',
            threshold=0.5, comparison='clip(alpha - 0.5); installed H3 and Reach alpha_test HLSL', required=True),
        backlight=dict(source=p.get('back_light'), target_binding=None,
                       policy='Retain source recipe; do not invent a Reach back_light socket'),
        wind='Independent engine_extern rule; cutout never depends on wind staticization', native_writes=False),
        confidence='MEDIUM', loss=['Reach flat foliage diffuse lighting approximates H3 SH/PRT diffuse lighting; no fabricated back_light socket'])


def cube_plan(bitmap, bindings):
    c = bitmap.get('cube_source', {})
    if (bitmap.get('type') != 'cube map' or bitmap.get('format', '').lower() not in {'dxt1','dxt5'}
        or bitmap.get('image_count') != 1 or bitmap.get('index') != 0 or bitmap.get('depth') != 1
        or bitmap.get('width') != bitmap.get('height') or bitmap.get('width', 0) <= 0
        or c.get('decoded_faces') != 6 or c.get('layout') != 'directx_cross_4x3'
        or not bitmap.get('dds') or not c.get('tiff')):
        return unknown('bitmap.single_cube', 'Need verified single-image BC1/BC3 six-face source pixels', bitmap)
    return decision('bitmap.single_cube', 'NATIVE_REBUILD', dict(source_bitmap=bitmap, usage=bindings,
        source_layout=c, target_type='Cube Map', target_usage='Environment Map',
        native_import='Decoded source TIFF cross -> normal Reach bitmap import; regenerate target compressed mip resources',
        writer_validation='Verify all six target faces/orientations against the decoded source face atlas before accepting native bitmap',
        source_mips='All retained in DDS; six base faces in TIFF', dimensions=[bitmap['width'], bitmap['height'], 6],
        substitute_2d=False))


def collision_evidence(bsp, record):
    a = bsp['environment_semantics']['authoring']; di = record['source_definition']
    d = a['definitions'][di]; mesh = d['collision_mesh']
    surfaces = [mesh['source_surfaces'][i] for i in record['affected']]
    mappings = d.get('surfaces')
    adjacent = []
    source_edges = mesh.get('edges_source', [])
    for surface in surfaces:
        neighbors = set()
        for ei in surface.get('ring', {}).get('source_edges', []):
            edge = source_edges[ei]
            neighbors.update(edge[k] for k in ('left surface','right surface')
                             if 0 <= edge[k] < len(mesh['source_surfaces']) and edge[k] != surface['source_surface'])
        adjacent.append(dict(source_surface=surface['source_surface'],
            neighbors=[dict(source_surface=i,material=mesh['source_surfaces'][i]['material'],
                            flags=mesh['source_surfaces'][i]['flags']) for i in sorted(neighbors)]))
    parts = a['render_meshes'][d['mesh index']]['parts']
    render_materials = []
    for part in parts:
        slot = part['render method index']
        valid = 0 <= slot < len(bsp['materials'])
        render_materials.append(dict(source_part=part['source_index'], source_material_slot=slot,
            source_shader=bsp['materials'][slot]['source_shader'] if valid else None,
            material_name=bsp['materials'][slot]['name'] if valid else None,
            source_material=a['materials'][slot] if valid and slot < len(a.get('materials', [])) else None,
            relationship='Owning definition render part; not a per-surface shard linkage',
            status='SOURCE_SLOT_RESOLVED' if valid else 'UNRESOLVED_SOURCE_INDEX'))
    return dict(source_bsp=bsp['source_tag'], source_bsp_index=bsp['bsp_index'],
        source_definition=di, source_mesh_index=d['mesh index'],
        definition_identity=bsp['source_tag']+f'#instanced geometry definitions[{di}]',
        definition_metadata={k:d.get(k) for k in ('checksum', 'bounding sphere center',
            'bounding sphere radius', 'breakable surface sets')},
        collision_surfaces=surfaces,
        adjacent_surfaces=adjacent,
        rings=[dict(surface=s['source_surface'], source_ring=s.get('ring'),
            positions=[mesh['vertices'][i]['position'] for i in s.get('ring',{}).get('decoded_vertices',[])]) for s in surfaces],
        render_correspondence=[mappings[s['source_surface']] for s in surfaces] if isinstance(mappings,list) else None,
        render_parts=parts, render_materials=render_materials,
        placements=[p for p in a['instances'] if p['source_index'] in record['affected_instances']],
        full_topology=dict(geometry_file=f"geometry/bsp_{bsp['bsp_index']:04}.json", definition=di,
            collision_mesh_sha256=sha(mesh), source_edge_count=len(mesh.get('edges_source',[])),
            source_vertex_count=len(mesh.get('vertices_source',[]))),
        collision_materials=a['collision_materials'])


def untextured_collision(evidence):
    surfaces = evidence['collision_surfaces']; mappings = evidence['render_correspondence']
    if (not surfaces or mappings is None or any(s['material'] != -1 or number(s['flags']) != 0 for s in surfaces)
        or any(m['structure_surface_to_triangle_mapping_count'] != 0 for m in mappings)
        or any(not r['source_ring'] or len(r['positions']) < 3 for r in evidence['rings'])):
        return unknown('collision.untextured_shell', 'Unassigned material alone is insufficient: require solid rings and zero source render correspondence', evidence)
    return decision('collision.untextured_shell', 'NATIVE_REBUILD', dict(source=evidence,
        semantic='Untextured solid instance collision shell; no authored rendering relationship',
        construct='Native instance collision proxy', face_mode='collision_only', global_material='default',
        preserve_source_ring_winding=True, preserve_placement_matrix=True, sky=False, shader_identity=None),
        confidence='MEDIUM', loss=['No source response material is assigned; target default collision response is used. No rendered material or sky is inferred.'])


COLLISION_FLAGS = {1: dict(source='two sided', target='face_sides=two_sided'),
                   2: dict(source='invisible', target='face_mode=sphere_collision_only'),
                   4: dict(source='climbable', target='ladder=True'),
                   8: dict(source='breakable', target='face_mode=breakable on linked render/collision geometry')}


def collision_flags(evidence):
    values = {number(s['flags']) for s in evidence['collision_surfaces']}
    if any(v & ~15 for v in values):
        return unknown('collision.surface_flags', 'Unknown collision behavior bit; cannot discard it', evidence)
    if any(v & 8 for v in values):
        # A separate breakable proxy is actively removed by Foundry to avoid a
        # Tool crash. Rebuilding shards/links is a structural requirement.
        return unknown('collision.surface_flags',
            'BSP breakable surfaces need verified shard/support and render-to-collision linkage. The flag does not establish whole-instance damage-state behavior. Foundry removes breakable mode from separate collision proxies; stripping breakability changes traversal.', evidence)
    bits = sorted({bit for v in values for bit in COLLISION_FLAGS if v & bit})
    return decision('collision.surface_flags', 'NATIVE_TRANSFORM', dict(source=evidence,
        flags=[COLLISION_FLAGS[b] for b in bits], preserve_collision_material_identity=True,
        construct='Instance collision proxy; two-sided winding retained',
        ray_collision='Disabled for invisible/sphere-only faces' if 2 in bits else 'Preserved',
        physical_collision='Preserved', ladder=4 in bits), confidence='MEDIUM' if 2 in bits else 'HIGH')


def lighting_material(bsp, index):
    m = bsp['environment_semantics']['authoring']['materials'][index]
    identity = bsp['materials'][index]['source_shader']
    if m['imported material index'] != -1:
        return unknown('lighting.material_properties', 'Invalid positive lighting index cannot be treated as an absent row', m)
    props = {p['type']['name']: p for p in m['properties']}
    if len(props) != len(m['properties']) or set(props) - {'lightmap resolution','lightmap transparency override','lightmap additive transparency'}:
        return unknown('lighting.material_properties', 'Unmapped or duplicate material property', m)
    target = {}
    if 'lightmap resolution' in props:
        target['lightmap_resolution_scale'] = number(props['lightmap resolution']['real-value'])
    if 'lightmap transparency override' in props:
        target['lightmap_transparency_override'] = bool(props['lightmap transparency override']['int-value'])
    if 'lightmap additive transparency' in props:
        packed = props['lightmap additive transparency']['long-value']
        if not 0 <= packed <= 0xFFFFFF:
            return unknown('lighting.material_properties', 'Unrecognized source packed transparency color', m)
        target['lightmap_additive_transparency'] = [(packed >> shift & 255)/255 for shift in (16,8,0)]
    return decision('lighting.material_properties', 'NATIVE_REBUILD', dict(source_material=m,
        source_shader=identity, source_material_slot=index, imported_lighting_index=None,
        target_material_properties=target, emission='No imported emissive row; preserve embedded properties, never index row -1',
        binding='Source shader identity plus source material slot/property signature; shader cache remains shared'))


def scenario_lights(plan):
    rows = plan['scenario_lights']['placements']
    result = []
    for row in rows:
        fields = [e['attributes'] for e in row['fields'] if e['element'] == 'field']
        def value(name):
            return next((f.get('value') for f in fields if f.get('name') == name), None)
        # The palette type and shape type have the same displayed field name.
        types = [f for f in fields if f.get('name') == 'type']
        if not types:
            return unknown('lighting.dynamic_placements', 'Missing ordered source light placement palette field', row)
        from .selection import index
        palette_index = index(types[0]['value'])
        if (value('lightmap light scale') not in {'0', '0.0'}
            or value('lightmap type') != 'use light tag setting' or value('lightmap flags') != '0'):
            return unknown('lighting.dynamic_placements', 'Placement requests a bake contribution or has unknown lightmap settings', row)
        palette = plan['scenario_lights']['palette']
        if not -1 <= palette_index < len(palette):
            return unknown('lighting.dynamic_placements', 'Invalid source light palette identity', row)
        result.append(dict(source_placement=row, palette_index=palette_index,
            source_light=None if palette_index == -1 else palette[palette_index]['source_tag'],
            classification='UNBOUND_SOURCE_PLACEMENT' if palette_index == -1 else 'RUNTIME_DYNAMIC_LIGHT',
            source_position=value('position'), source_rotation=value('rotation'),
            bsp_membership='Deferred source spatial query; no BSP inferred from palette index or nearby position',
            static_bake_scale=0, target_static_instances=0))
    return decision('lighting.dynamic_placements', 'RUNTIME_LATER', dict(placements=result,
        palette=plan['scenario_lights']['palette'], target='Preserve runtime .light recipes and placement identity for later light/object work',
        static_bake='BSP lighting-info definitions/instances are preserved with their owning BSP independently',
        preserved_static_instances=sum(len(l['instances']) for l in plan['lighting_by_bsp'])),
        loss=['Runtime light gels, modulation and dynamic illumination are deferred; no source static bake instances are removed'])


def resolve_record(record, plan, bsps, shaders):
    field, source = record['source_field'], record['source_tag']
    by_bsp = {b['source_tag']: b for b in bsps}
    if field == 'parameters[].functions/extern':
        # Bake power/color exist independently of the visual shader snapshot.
        materials = [m for b in plan['bsps'] for m in b['materials'] if m.get('source_shader') == source]
        bake_preserved = bool(materials) and all('lighting' in m for m in materials)
        required = any(float(m.get('lighting', {}).get('emissive power',0)) > 0 for m in materials)
        return material_functions(shaders['shaders'][source], record['affected'], bake_preserved, required)
    if field.endswith('parts[].part type'):
        b = by_bsp[source]; mi = int(re.search(r'meshes\[(\d+)\]', field)[1])
        part = b['environment_semantics']['authoring']['render_meshes'][mi]['parts'][record['affected'][0]]
        shader = shaders['shaders'][b['materials'][part['render method index']]['source_shader']]
        result = render_part(part, shader)
        result['target_authoring_plan'].update(source_mesh=mi, source_shader=shader['source'])
        return result
    if field.endswith('collision info.surfaces[].material'):
        return untextured_collision(collision_evidence(by_bsp[source], record))
    if field.endswith('collision info.surfaces[].flags'):
        return collision_flags(collision_evidence(by_bsp[source], record))
    if field == 'shader group/status':
        shader = shaders['shaders'][source]
        if shader.get('status') == 'resolved_snapshot':
            if shader['group'] == 'rmtr': return terrain_plan(shader)
            if shader['group'] == 'rmfl': return foliage_plan(shader)
    if field == 'bitmap image form':
        key = record['affected'][0]
        bindings = [dict(source_shader=s, parameter=p['name']) for s,v in shaders['shaders'].items()
                    for p in v['parameters'] if p.get('bitmap') == key]
        return cube_plan(shaders['bitmaps'][key], bindings)
    if field == 'materials[].imported material index':
        return lighting_material(by_bsp[source], record['affected'][0])
    if field == 'light volumes':
        return scenario_lights(plan)
    if field == 'material info':
        return unknown('lighting.emissive_frustum',
            'Need H3 frustum angular weighting/blend and area-power normalization to reproduce it with Reach focus or surface-derived analytical emitters; numeric angle substitution is not evidence.', record)
    if field == 'seams[].selected BSP owners':
        return unknown('seam.inactive_neighbor',
            'Need a Reach authoring construct preserving the H3 inactive-neighbor seam boundary collision/visibility without a second active BSP or fabricated closure.', record)
    return unknown('source.unknown', 'No reusable rule matches this source contract', record)


def family(record):
    field=record['source_field']
    if field.endswith('collision info.surfaces[].material'): return 'Unassigned instance collision materials'
    if field.endswith('collision info.surfaces[].flags'): return 'Collision surface flags'
    if field.endswith('parts[].part type'): return 'Compiled render-part categories'
    return {'parameters[].functions/extern':'Material functions / externs',
            'shader group/status':'Native terrain / foliage materials',
            'bitmap image form':'Active image forms',
            'material info':'Emissive frustum / flags',
            'materials[].imported material index':'Lighting-material relationship',
            'seams[].selected BSP owners':'Unmatched active seam',
            'light volumes':'Scenario light volumes'}.get(field, field)


def report(records, decisions, baseline=None):
    current = {}
    for record, result in zip(records, decisions, strict=True):
        rid = record_id(record)
        if rid in current:
            raise ValueError('Duplicate original source contract identity: '+rid)
        current[rid] = dict(original_record_id=rid, category=family(record),
                            original_record=record, **result)
    originals = records if baseline is None else baseline
    original_ids = [record_id(r) for r in originals]
    if len(set(original_ids)) != len(original_ids):
        raise ValueError('Duplicate baseline contract identity')
    for record, rid in zip(originals, original_ids):
        if rid not in current:
            current[rid] = dict(original_record_id=rid, category=family(record), original_record=record,
                **unknown('source.unknown', 'Original diagnostic disappeared from extraction; explicit identity migration/evidence is required', record))
    original_set = set(original_ids)
    for rid,row in current.items():
        row['accounting_scope'] = 'original' if rid in original_set else 'new_source_contract'
    counts = {c: sum(current[r]['resolution_class'] == c for r in original_ids) for c in CLASSES}
    if sum(counts.values()) != len(originals):
        raise ValueError('Source-contract accounting did not balance')
    def walk(value):
        if isinstance(value, dict):
            if 'semantic_rule_id' in value: yield value['semantic_rule_id']
            for item in value.values(): yield from walk(item)
        elif isinstance(value, list):
            for item in value: yield from walk(item)
    used = sorted(set(walk(list(current.values()))))
    before_after = []
    for category in sorted({family(r) for r in originals}):
        rows = [current[r] for r in original_ids if current[r]['category'] == category]
        before_after.append(dict(category=category, original=len(rows),
                                 resolved=sum(not r['still_blocking'] for r in rows), blocking=sum(r['still_blocking'] for r in rows)))
    return dict(format='foundry.h3-source-semantic-resolution', version=1,
        original_records=len(originals), current_observations=len(records), new_records=len(set(current)-original_set),
        accounting=counts, accounting_balanced=True, before_after=before_after,
        unique_semantic_rules=len(used), semantic_rules=used, mapping_catalog_sha256=sha(CATALOG),
        blocking_records=sum(r['still_blocking'] for r in current.values()),
        native_writes=False, native_validation='NOT_RUN', runtime_acceptance='NOT_TESTED',
        records=[current[r] for r in sorted(current)])


def resolve(plan, bsps, shaders, baseline=None):
    originals = deepcopy(plan['unsupported'])
    decisions = []
    for record in originals:
        try:
            decisions.append(resolve_record(record, plan, bsps, shaders))
        except (KeyError, ValueError, TypeError, IndexError, struct.error) as exc:
            decisions.append(unknown('source.unknown', f'Rule precondition failed: {exc}', record))
    resolution = report(originals, decisions, baseline)
    usage = plan.get('source_dependencies', {}).get('shader_usage', {})
    for row in resolution['records']:
        original = row['original_record']; source = original['source_tag'].replace('\\','/')
        row['provenance'] = dict(source_tag=original['source_tag'], source_sha256=plan['source']['hashes'].get(source),
            source_scenario=plan['selection']['source_scenario'], zone_set=plan['selection']['source_zone_set'],
            zone_set_mask=plan['selection']['source_bsp_mask'],
            selected_bsp_indices=[b['source_index'] for b in plan['bsps']],
            usage_reference=('source-dependencies.json#/shader_usage/'+source.replace('~','~0').replace('/','~1')) if source in usage else None)
    resolution['function_inventory'] = function_inventory(shaders)
    plan['source_contract_observations'] = originals
    plan['source_semantic_resolution'] = resolution
    plan['unsupported'] = [dict(r['original_record'], original_record_id=r['original_record_id'],
        semantic_rule_id=r['semantic_rule_id'], resolution_class=r['resolution_class'],
        missing_fact=r['target_authoring_plan'].get('missing_fact')) for r in resolution['records'] if r['still_blocking']]
    by_material = {m['source_shader']:m for m in plan['materials']}
    for r in resolution['records']:
        if r['still_blocking']: continue
        original = r['original_record']; source = original['source_tag']
        if source in by_material:
            by_material[source].setdefault('semantic_authoring', []).append(r)
            extension = r['target_authoring_plan'].get('target_tag_group')
            if extension:
                m = by_material[source]; m['destination'] = m['destination'].rsplit('.',1)[0]+'.'+extension
        if r['semantic_rule_id'] == 'bitmap.single_cube':
            plan['bitmaps'][original['affected'][0]] = r['target_authoring_plan']
    plan['mappings_used'] += resolution['semantic_rules']
    return resolution


def reconcile_baseline(plan, baseline):
    observed = plan['source_contract_observations']
    existing = {r['original_record_id']: r for r in plan['source_semantic_resolution']['records']}
    results = [{k:v for k,v in existing[record_id(o)].items()
                if k not in {'original_record_id', 'original_record', 'accounting_scope', 'category'}} for o in observed]
    resolution = report(observed, results, baseline)
    resolution['function_inventory'] = plan['source_semantic_resolution'].get('function_inventory', [])
    plan['source_semantic_resolution'] = resolution
    plan['unsupported'] = [dict(r['original_record'], original_record_id=r['original_record_id'],
        semantic_rule_id=r['semantic_rule_id'], resolution_class=r['resolution_class'],
        missing_fact=r['target_authoring_plan'].get('missing_fact')) for r in resolution['records'] if r['still_blocking']]


def function_inventory(shaders):
    """Aggregate function semantics, keeping each source recipe/value and usage link."""
    groups = {}
    for source,shader in sorted(shaders['shaders'].items()):
        authored = {p['name']:p for p in shader.get('authored_parameters',[])}
        for parameter in shader.get('parameters',[]):
            if not (parameter.get('has_functions') or parameter.get('extern')): continue
            functions = authored.get(parameter['name'],{}).get('functions',[])
            signatures = []
            for f in functions:
                try: kind = function_header(f)['type']
                except (ValueError, KeyError, TypeError, struct.error): kind = 'UNDECODED'
                signatures.append(dict(function_type=kind,channel=f.get('channel'),input=f.get('input'),range=f.get('range')))
            key = canonical(dict(parameter=parameter['name'],parameter_type=parameter['type'],
                                 extern=parameter.get('extern'),functions=signatures))
            if key not in groups:
                groups[key] = dict(json.loads(key), owners=[])
            groups[key]['owners'].append(dict(source_shader=source, source_parameter=parameter,
                source_function_sha256=[sha(f) for f in functions],
                usage_reference='source-dependencies.json#/shader_usage/'+source.replace('~','~0').replace('/','~1')))
    return [dict(groups[k],source_call_count=len(groups[k]['owners'])) for k in sorted(groups)]


def markdown(resolution):
    lines = ['# H3 environment source semantic resolution', '',
             f"Original records: **{resolution['original_records']}**. Blocking records: **{resolution['blocking_records']}**.",
             f"Unique semantic rules: **{resolution['unique_semantic_rules']}**. Accounting balanced: {resolution['accounting_balanced']}.",
             '', 'Source planning only. No Reach data/tags written; Tool import, Faux and runtime validation were not run.', '',
             '| Original source field | Before | Resolved | Blocking |', '|---|---:|---:|---:|']
    for row in resolution['before_after']:
        lines.append(f"| {row['category']} | {row['original']} | {row['resolved']} | {row['blocking']} |")
    lines += ['', 'Resolution classes:', '']
    lines += [f'- {name}: {count}' for name,count in resolution['accounting'].items()]
    lines += ['', 'Remaining blockers:', '']
    for row in resolution['records']:
        if row['still_blocking']:
            original = row['original_record']
            lines += [f"- `{row['original_record_id']}` — `{original['source_tag']}` / `{original['source_field']}`: {row['reason']}"]
    lines += ['', 'Fidelity losses retained in the plan:', '']
    lines += ['- '+loss for loss in sorted({loss for row in resolution['records'] for loss in row['fidelity_loss']})]
    lines += ['', 'Each record in source-semantic-resolution.json includes the original diagnostic, rule, source evidence, confidence and target authoring plan.',
              'Evidence labeled inference is not documentation or runtime validation. Breakable proxies, unknown directional emissive weighting and inactive-neighbor closure remain explicit gates.', '']
    return '\n'.join(lines)

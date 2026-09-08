"""Source contracts shared by environment planning and the native authoring worker.

Every rejection names the source field and affected records. Compiled spatial
indices are evidence for reconstruction, never target resource payloads.
"""
from collections import defaultdict
import math
import hashlib

from . import fixtures
from .selection import optional_block, index


def number(value):
    if isinstance(value, dict):
        if 'values' in value:
            if len(value['values']) != 1 or value['values'][0] is None:
                raise ValueError('Expected finite source scalar')
            return value['values'][0]
        return value['value']
    return value


def vector(value):
    result = value['values'] if isinstance(value, dict) else [float(v) for v in value.split(',')]
    if any(v is None or not math.isfinite(v) for v in result):
        raise ValueError('Nonfinite source vector')
    return result


def issue(source, field, affected, reason, **extra):
    return dict(source_tag=source, source_field=field, count=len(affected), affected=affected,
                reason=reason, status='UNSUPPORTED', **extra)


def field_evidence(node):
    """Keep ordered, duplicate-named Tool fields; opaque function bytes stay evidence."""
    result = []
    for element in node:
        row = dict(element=element.tag, attributes=dict(element.attrib))
        if element.get('type') == 'data':
            value = row['attributes'].pop('value', '').encode('utf-8')
            row['opaque_function_data'] = dict(encoded_bytes=len(value), sha256=hashlib.sha256(value).hexdigest(),
                                                policy='Retained in source XML; not executed or copied to target')
        if len(element):
            row['children'] = field_evidence(element)
        result.append(row)
    return result


def scenario_light_plan(root, selection, light_xmls):
    """Inventory candidate .light tags without inventing zone/BSP membership."""
    palette, placements, problems = [], [], []
    for entry in selection.get('light_palette', []):
        source = entry['source_tag']
        if source is None:
            palette.append(dict(entry, status='EMPTY_SOURCE_PALETTE_ENTRY'))
            continue
        tag = light_xmls.get(source)
        if tag is None:
            problems.append(issue(source, 'light volumes palette[].name', [entry['source_index']],
                                  'Source light tag evidence was not decoded'))
            continue
        if tag.get('group') != 'light' or tag.get('id', '').replace('\\', '/')+'.light' != source:
            raise ValueError('Source .light identity differs from the scenario palette')
        palette.append(dict(entry, fields=field_evidence(tag), status='SOURCE_EVIDENCE_ONLY'))
    for i, row in enumerate(optional_block(root, 'light volumes')):
        # This format flattens nested structs with repeated "type" and "flags"
        # field names. Preserve their order rather than silently merging them.
        placements.append(dict(source_index=i, fields=field_evidence(row), membership='UNRESOLVED'))
    if placements:
        problems.append(issue(selection['source_scenario'], 'light volumes', list(range(len(placements))),
            'Scenario light-volume BSP/zone membership and .light functions require a verified adapter; these are not viewport lights',
            source_palette=[p['source_tag'] for p in palette]))
    return dict(palette=palette, placements=placements, status='SOURCE_EVIDENCE_ONLY'), problems


def matrix(row):
    basis = [vector(row[n]) for n in ('forward', 'left', 'up')]
    p, scale = vector(row['position']), number(row['scale'])
    if any(len(v) != 3 for v in [*basis, p]) or not math.isfinite(scale) or scale <= 0:
        raise ValueError('Unsupported source instance basis/scale')
    for i in range(3):
        for j in range(3):
            if abs(sum(a*b for a,b in zip(basis[i],basis[j])) - (i == j)) > 0.001:
                raise ValueError('Nonorthogonal source instance basis')
    det = sum(basis[0][i]*(basis[1][(i+1)%3]*basis[2][(i+2)%3] -
                          basis[1][(i+2)%3]*basis[2][(i+1)%3]) for i in range(3))
    if det < 0:
        raise ValueError('Mirrored instance requires a winding adapter')
    return [[basis[j][i]*scale for j in range(3)]+[p[i]*100] for i in range(3)]+[[0,0,0,1]]


def instance_plan(bsp):
    """Match render placements by authored identity AND transform, retaining collision-only definitions."""
    from .model import world_point
    a = bsp['environment_semantics']['authoring']
    candidates = defaultdict(list)
    decoded = {r['id']: r for r in bsp['instances']}
    if len(decoded) != len(bsp['instances']):
        raise ValueError('Duplicate decoded instance identity')
    for row in bsp['instances']:
        if row['object'] >= 0:
            candidates[row['name']].append(row)
    placements, used, problems = [], set(), []
    for row in a['instances']:
        i, di = row['source_index'], row['instance definition']
        if type(di) is not int or not 0 <= di < len(a['definitions']):
            problems.append(issue(bsp['source_tag'], 'instanced geometry instances[].instance definition', [i], 'Invalid definition index'))
            continue
        definition = a['definitions'][di]
        mi = definition['mesh index']
        if type(mi) is not int or not 0 <= mi < len(a['render_meshes']):
            problems.append(issue(bsp['source_tag'], f'instanced geometries definitions[{di}].mesh index',
                                  [i], 'Invalid source render mesh index', source_value=mi))
            continue
        source_mesh = a['render_meshes'][mi]
        expected_render = any(p['index count'] for p in source_mesh['parts'])
        mat = matrix(row)
        p = [mat[k][3] for k in range(3)]
        matches = [c for c in candidates[row['name']] if c['id'] not in used and
                   max(abs(x-y) for x,y in zip(c['position'],p)) < 0.01]
        render = None
        if expected_render:
            if len(matches) != 1:
                problems.append(issue(bsp['source_tag'], 'instanced geometry instances[].render mesh', [i],
                                      'Missing/ambiguous decoded placement identity and transform', source_name=row['name']))
            else:
                candidate = matches[0]
                # Match the whole frame, including parent and pivot transforms.
                # Position alone cannot prove a repeated definition's rotation.
                for probe in ([0, 0, 0], [100, 0, 0], [0, 100, 0], [0, 0, 100]):
                    expected = [sum(mat[k][j]*probe[j] for j in range(3))+mat[k][3] for k in range(3)]
                    actual = world_point(candidate, probe, decoded)
                    if max(abs(x-y) for x,y in zip(actual,expected)) > 0.02:
                        problems.append(issue(bsp['source_tag'], 'instanced geometry instances[].transform', [i],
                            'Decoded placement frame differs from the authored source basis', source_name=row['name']))
                        break
                render = candidate['object']; used.add(candidate['id'])
        flags = number(row['flags'])
        if flags & ~10:
            problems.append(issue(bsp['source_tag'], 'instanced geometry instances[].flags', [i],
                                  'Unmapped instance flag bits', source_value=row['flags']))
        collidable = bool(flags & 8) and not bool(flags & 2)
        placements.append(dict(source_index=i, name=row['name'], source_definition=di,
                               render_object=render, collision_definition=di if collidable else None,
                               matrix=mat, source_fields=row,
                               strategy='Shared local render definition and decoded collision proxy; authored instance matrix'))
    return dict(placements=placements, used_render_instances=sorted(used),
                definition_count=len(a['definitions']), source_instance_count=len(a['instances']),
                collision_only_count=sum(p['render_object'] is None and p['collision_definition'] is not None for p in placements)), problems


def audit_bsp(bsp):
    a = bsp.get('environment_semantics', {}).get('authoring')
    if not a or a.get('version') != 1:
        return [issue(bsp['source_tag'], 'environment_semantics.authoring', [bsp.get('bsp_index')],
                      'Source helper lacks the complete environment contract; rebuild the helper')]
    problems = []
    # Unlike structure material=-1 sky boundaries, instance collision material=-1
    # has no proven sky meaning. Never route it through map_collision's sky path.
    active_definitions = defaultdict(list)
    for row in a['instances']:
        if number(row['flags']) & 8 and not number(row['flags']) & 2:
            active_definitions[row['instance definition']].append(row['source_index'])
    for di, instances in active_definitions.items():
        definition = a['definitions'][di]
        if 'collision_mesh' not in definition:
            problems.append(issue(bsp['source_tag'], f'instanced geometry definitions[{di}].collision info', instances,
                                  'Source helper does not decode instance collision'))
            continue
        categories = defaultdict(list)
        for surface in definition['collision_mesh']['source_surfaces']:
            flags = number(surface['flags'])
            if flags & ~1:
                categories[('flags', str(surface['flags']))].append(surface['source_surface'])
            if surface['material'] < 0:
                categories[('material', str(surface['material']))].append(surface['source_surface'])
        for (field, value), surfaces in categories.items():
            problems.append(issue(bsp['source_tag'], f'instanced geometry definitions[{di}].collision info.surfaces[].{field}',
                surfaces, ('No verified Reach authoring adapter for these collision flags' if field == 'flags' else
                           'Unassigned instance collision material is not a structure sky surface; source meaning must be resolved'),
                source_value=value, affected_instances=instances, source_definition=di))
    for mesh in a['render_meshes']:
        for part in mesh['parts']:
            if number(part['part flags']) & ~2:
                problems.append(issue(bsp['source_tag'], f"render geometry.meshes[{mesh['source_index']}].parts[].part flags",
                                      [part['source_index']], 'Unmapped render surface flags', source_value=part['part flags']))
            if part['part type'] != 2 and part['index count']:
                problems.append(issue(bsp['source_tag'], f"render geometry.meshes[{mesh['source_index']}].parts[].part type",
                    [part['source_index']], 'Non-opaque compiled part category needs a verified authoring mapping',
                    source_value=part['part type'], affected_triangles=part['index count']//3))
    for name in ('weather',):
        if a[name]:
            problems.append(issue(bsp['source_tag'], name, list(range(len(a[name]))), 'No verified authored volume adapter'))
    return problems


def portal_plan(bsp):
    a = bsp['environment_semantics']['authoring']
    result, problems = [], []
    for p in a['portals']:
        i, flags = p['source_index'], number(p['flags'])
        front, back = p['front cluster'], p['back cluster']
        if any(c < -1 or c >= len(a['clusters']) for c in (front,back)):
            raise ValueError('Invalid source portal cluster relationship')
        if flags & ~12:
            problems.append(issue(bsp['source_tag'], 'cluster portals[].flags', [i],
                                  'Unmapped portal flags', source_value=p['flags']))
        vertices = [vector(v['point']) for v in p['vertices']]
        if len(vertices) < 3:
            raise ValueError('Degenerate source portal polygon')
        result.append(dict(source_index=i, source_front_cluster=front, source_back_cluster=back,
                           vertices_world=vertices, mesh_type='_connected_geometry_mesh_type_portal',
                           portal_type='_connected_geometry_portal_type_no_way' if flags & 8 else '_connected_geometry_portal_type_two_way', portal_is_door=bool(flags & 4),
                           source_flags=p['flags'], strategy='Source polygon -> native Reach portal authoring; Tool rebuilds PVS'))
    return result, problems


def design_plan(root, source, scenario):
    if root.get('group') != 'structure_design' or root.get('id', '').replace('\\','/')+'.structure_design' != source:
        raise ValueError('Design source identity differs from scenario relationship')
    problems, meshes = [], []
    for e in root:
        if e.tag == 'block' and len(e) and e.get('name') not in {'soft ceiling mopp code block', 'soft ceilings block'}:
            problems.append(issue(source,e.get('name'),list(range(len(e))),'Unsupported nonempty structure-design block'))
    for i, row in enumerate(fixtures.block(root,'soft ceilings block')):
        kind, name = fixtures.field(row,'type'), fixtures.field(row,'name')
        if kind not in {'acceleration','soft kill','slip surface'}:
            problems.append(issue(source,'soft ceilings block[].type',[i],'Unmapped design boundary type',source_value=kind))
            continue
        faces = []
        for t in fixtures.block(row,'soft ceiling triangles'):
            faces.append([vector(fixtures.field(t,f'vertex{j}')) for j in range(3)])
        settings = [r for r in optional_block(scenario,'soft ceilings') if fixtures.field(r,'name') == name]
        if len(settings)>1:
            raise ValueError('Ambiguous scenario soft ceiling name')
        flags = int(fixtures.field(settings[0],'flags','0')) if settings else 0
        if flags & ~7:
            problems.append(issue(source,'scenario soft ceilings[].flags',[i],'Unsupported boundary ignore flags',source_value=flags))
        meshes.append(dict(source_index=i,name=name,source_type=kind,triangles_world=faces,
                           source_flags=flags,mesh_type='_connected_geometry_mesh_type_boundary_surface',
                           boundary_surface_type={'acceleration':'SOFT_CEILING','soft kill':'SOFT_KILL','slip surface':'SLIP_SURFACE'}[kind]))
    return dict(source_tag=source,meshes=meshes,source_triangles=sum(len(m['triangles_world']) for m in meshes),
                strategy='Decoded boundary triangles -> Foundry boundary surfaces -> Reach structure_design; regenerate MOPP'),problems


def static_lighting(root, source):
    semantics = fixtures.lighting_semantics(root)
    definitions, instances, problems = [], [], []
    for i,row in enumerate(semantics['light_definitions']):
        kind, shape, flags = row['type'],row['shape'],int(row['flags'])
        if kind not in {'omni','spot','directional'} or shape not in {'circle','rectangle'} or flags & ~3:
            problems.append(issue(source,'generic light definitions',[i],'Unmapped light type, shape, or flags',source_value=row))
            continue
        color=vector(row['color']);intensity=float(row['intensity'])
        if len(color)!=3 or min(color)<0 or not math.isfinite(intensity) or intensity<0:
            raise ValueError('Invalid source static light color/intensity')
        definitions.append(dict(source_index=i,type={'omni':0,'spot':1,'directional':2}[kind],
            shape={'circle':0,'rectangle':1}[shape],color=color,intensity=intensity,flags=flags,
            hotspot_size=math.degrees(float(row['hotspot size'])),
            hotspot_cutoff=math.degrees(float(row['hotspot falloff size'])),hotspot_falloff=1.0,
            near_attenuation=vector(row['near attenuation bounds']),far_attenuation=vector(row['far attenuation bounds']),
            aspect=float(row['aspect']),source_fields=row))
    for i,row in enumerate(semantics['light_instances']):
        index=int(row['definition index'])
        if not 0<=index<len(semantics['light_definitions']):
            raise ValueError('Source static light refers to absent definition')
        instances.append(dict(source_index=i,definition_index=index,origin=vector(row['origin']),
                              forward=vector(row['forward']),up=vector(row['up'])))
    for i,row in enumerate(semantics['materials']):
        if float(row['emissive power']) and (float(row.get('frustum blend',0)) or int(row['flags']) & ~1):
            problems.append(issue(source,'material info',[i],'Unmapped active emissive frustum or material flags',source_value=row))
    regions = [dict(name=fixtures.field(r,'name'),triangles_world=[[vector(fixtures.field(t,f'v{i}')) for i in range(3)]
               for t in fixtures.block(r,'triangles')]) for r in optional_block(root,'regions')]
    return dict(source_tag=source,source_semantics=semantics,definitions=definitions,instances=instances,regions=regions,
                counts=dict(source_generic_static_lights=len(instances),source_light_definitions=len(definitions),
                            source_emissive_material_rows=sum(float(r['emissive power'])!=0 for r in semantics['materials'])),
                strategy='Source static light definitions and instances -> native Foundry lighting-info authoring before Faux'),problems


def seam_plan(root, bsps):
    """Join the source seam-table index AND identifier, never by proximity.

    Voi reuses one identifier for several distinct seams. The BSP's parallel
    seam table and collision-material seam mapping index disambiguate it.
    """
    result, problems = [], []
    source_seams=fixtures.block(root,'seams')
    for bsp in bsps:
        if len(bsp['environment_semantics']['authoring']['seams'])!=len(source_seams):
            raise ValueError('BSP seam mapping table does not cover the source global seam table')
    for i,row in enumerate(source_seams):
        identity=[int(fixtures.field(row,f'seam_id{k}')) for k in range(4)]
        owners=[]
        for bsp in bsps:
            for s in bsp['environment_semantics']['authoring']['seams']:
                sid=s['seams identifier']
                if (s['source_index']==i and [sid[f'seam_id{k}'] for k in range(4)]==identity
                        and any(identity) and s['cluster mapping']):
                    owners.append(dict(source_bsp_index=bsp['bsp_index'],source_bsp=bsp['source_tag'],
                                       cluster_mapping=s['cluster mapping'],edge_mapping=s['edge mapping']))
        if not owners: continue
        original=fixtures.block(row,'original vertices')
        vertices=[vector(fixtures.field(v,'original vertex')) for v in original]
        point_map={int(fixtures.field(v,'final point index')):j for j,v in enumerate(original)}
        final_points=[vector(fixtures.field(v,'final point')) for v in fixtures.block(row,'points')]
        triangles=[]; invalid=[]; correspondence=[]
        for ti,triangle in enumerate(fixtures.block(row,'triangles')):
            ids=[index(fixtures.field(triangle,f'final point{k}')) for k in range(3)]
            # Use the authored index relationship, never a nearest-point join.
            # H3 Tool's six-significant-digit XML plus seam compilation can
            # differ by 0.0001 world units. Retain ORIGINAL coordinates and
            # record that bounded difference; larger/ambiguous joins block.
            if (len(point_map)!=len(original) or any(k not in point_map or not 0<=k<len(final_points)
                or math.dist(final_points[k],vertices[point_map[k]])>1e-4+1e-10 for k in ids)):
                invalid.append(ti)
                continue
            triangles.append([point_map[k] for k in ids])
        if invalid:
            problems.append(issue(root.get('id')+'.structure_seams','seams[].original vertices',[i],
                'Compiled seam vertices have no bounded explicit original authoring correspondence',
                source_triangles=invalid))
        for k,j in sorted(point_map.items()):
            if 0<=k<len(final_points) and final_points[k]!=vertices[j]:
                correspondence.append(dict(final_point_index=k,original_vertex_index=j,
                    original_world=vertices[j],compiled_world=final_points[k],
                    distance_world=math.dist(final_points[k],vertices[j])))
        if len(owners)!=2:
            problems.append(issue(root.get('id')+'.structure_seams','seams[].selected BSP owners',[i],
                                  'A seam has no selected partner; source activation and collision state require resolution',source_owners=owners))
        result.append(dict(source_index=i,identifier=identity,owners=owners,vertices_world=vertices,triangles=triangles,
                           strategy='Paired original source seam geometry -> Reach connected-geometry seam authoring'))
        if correspondence:
            result[-1]['source_vertex_correspondence']=dict(method='Explicit authored final point index',
                native_coordinates='Original authoring vertices',tolerance_world=1e-4,rows=correspondence)
    return result,problems

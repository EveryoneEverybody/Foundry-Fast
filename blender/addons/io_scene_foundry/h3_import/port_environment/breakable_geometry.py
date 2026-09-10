"""Prove local render/collision equivalence before planning unified breakable faces.

This is deliberately a bounded geometry proof, not a nearest-face guess. It
accepts triangles/convex quads with identical triangulated coverage and matching
material identity. Opposite render copies may be represented by a two-sided face
only when their corner attributes agree. No geometry is written or modified.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import math

from .authoring import number
from .breakables import shader_reference


def sub(a, b):
    return tuple(x-y for x, y in zip(a, b, strict=True))


def dot(a, b):
    return sum(x*y for x, y in zip(a, b, strict=True))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def length(a):
    return math.sqrt(dot(a, a))


def cycle(values):
    values = tuple(values)
    return min(values[i:]+values[:i] for i in range(len(values)))


def edges(values):
    return [tuple(sorted((v, values[(i+1) % len(values)]))) for i, v in enumerate(values)]


def prove(render, collision, material_shaders, collision_materials, *, units):
    if units != 'ass_100_per_world_unit':
        raise ValueError('Unverified local geometry/plane unit conversion')
    rv = render['vertices']; triangles = render['triangles']; surfaces = collision['source_surfaces']
    if not rv or not triangles or not surfaces:
        raise ValueError('Unified breakable geometry needs render faces and collision rings')
    if any(number(s['flags']) != 9 for s in surfaces):
        raise ValueError('Unified rule requires two-sided breakable surfaces throughout the definition')
    # Only EXACT render-position duplicates are grouped. Nearby distinct render
    # positions remain distinct; an ambiguous collision match is rejected.
    positions = sorted({tuple(v['position']) for v in rv})
    if any(len(p) != 3 or not all(math.isfinite(v) for v in p) for p in positions):
        raise ValueError('Invalid render coordinates')
    extent = max(abs(v) for p in positions for v in p)
    # Eight float32 ULPs at this local magnitude cover decode roundoff, not
    # artistic welding. The threshold and measured errors are part of the IR.
    tolerance = 8 * 2.0 ** (math.frexp(max(extent, 1.0))[1]-24)
    ids = {p:i for i,p in enumerate(positions)}
    vertex_ids = [ids[tuple(v['position'])] for v in rv]
    groups = defaultdict(list)
    face_ids = []
    for ti, t in enumerate(triangles):
        if any(i < 0 or i >= len(rv) for i in t['vertices']):
            raise ValueError(f'Invalid render triangle indices {ti}')
        face = tuple(vertex_ids[i] for i in t['vertices'])
        if len(face) != 3 or len(set(face)) != 3:
            raise ValueError(f'Degenerate render triangle {ti}')
        face_ids.append(face); groups[tuple(sorted(face))].append(ti)
    for key, indices in groups.items():
        if len(indices) != 2 or cycle(face_ids[indices[0]]) != cycle(tuple(reversed(face_ids[indices[1]]))):
            raise ValueError(f'Render face {indices[0]} lacks one exact opposite-facing copy')
        first, second = (triangles[i] for i in indices)
        if {k:v for k,v in first.items() if k != 'vertices'} != {k:v for k,v in second.items() if k != 'vertices'}:
            raise ValueError('Opposite render copies use different materials')
        va = {vertex_ids[i]:rv[i] for i in first['vertices']}
        vb = {vertex_ids[i]:rv[i] for i in second['vertices']}
        for vi in key:
            a, b = va[vi], vb[vi]
            if {k:v for k,v in a.items() if k != 'normal'} != {k:v for k,v in b.items() if k != 'normal'}:
                raise ValueError(f'Opposite render copies have different UV/color/weights at face {indices[0]}')
            if length(tuple(x+y for x,y in zip(a['normal'], b['normal'], strict=True))) > 1e-5:
                raise ValueError('Opposite render-copy normals are not opposite')
    unique_faces = sorted(groups, key=lambda k:groups[k][0])
    rings, max_vertex_error, max_plane_error = [], 0.0, 0.0
    matched_cache = {}
    for surface in surfaces:
        si = surface['source_surface']; ring = surface.get('ring') or {}
        points = [tuple(collision['vertices'][i]['position']) for i in ring.get('decoded_vertices', [])]
        if len(points) not in (3, 4) or len(ring.get('source_edges', [])) != len(points):
            raise ValueError(f'Collision surface {si} needs a decoded triangle/quad ring with edges')
        ring_ids = []
        for point in points:
            if point not in matched_cache:
                candidates = [(length(sub(point,p)),i) for i,p in enumerate(positions) if length(sub(point,p)) <= tolerance]
                if len(candidates) != 1:
                    raise ValueError(f'Collision surface {si}: {len(candidates)} render vertices within local roundoff tolerance')
                matched_cache[point] = candidates[0]
            distance, vi = matched_cache[point]
            max_vertex_error = max(max_vertex_error, distance); ring_ids.append(vi)
        if len(set(ring_ids)) != len(ring_ids):
            raise ValueError(f'Collision surface {si} has a collapsed ring')
        normal = cross(sub(points[1],points[0]), sub(points[2],points[0]))
        magnitude = length(normal)
        if magnitude <= tolerance*tolerance:
            raise ValueError(f'Collision surface {si} is degenerate')
        normal = tuple(v/magnitude for v in normal)
        if any(abs(dot(normal,sub(p,points[0]))) > tolerance for p in points):
            raise ValueError(f'Collision surface {si} is nonplanar')
        if any(dot(cross(sub(points[(i+1)%len(points)],p),
                         sub(points[(i+2)%len(points)],points[(i+1)%len(points)])),normal) <= 0
               for i,p in enumerate(points)):
            raise ValueError(f'Collision surface {si} is not a strictly convex ring')
        plane_index = surface['plane'] & 0x7fff
        # The decoder may expose the oriented uint16 plane reference as int16.
        if not -0x8000 <= surface['plane'] <= 0xffff or plane_index >= len(collision['planes_source']):
            raise ValueError(f'Collision surface {si} has an invalid plane index')
        plane = collision['planes_source'][plane_index]['plane']['values']
        scale = length(plane[:3])
        if len(plane) != 4 or not all(math.isfinite(v) for v in plane) or scale == 0:
            raise ValueError(f'Collision surface {si} has an invalid source plane')
        plane_error = max(abs(dot(plane[:3],p)-plane[3]*100)/scale for p in points)
        max_plane_error = max(max_plane_error,plane_error)
        if plane_error > tolerance:
            raise ValueError(f'Collision surface {si} does not lie on its source plane')
        candidates = [k for k in unique_faces if set(k) <= set(ring_ids)]
        if len(candidates) != len(ring_ids)-2:
            raise ValueError(f'Collision surface {si} lacks complete render triangulation')
        counts = Counter(e for k in candidates for e in edges(k))
        boundary = {e for e,n in counts.items() if n == 1}
        if boundary != set(edges(ring_ids)) or any(n not in (1,2) for n in counts.values()):
            raise ValueError(f'Collision surface {si} render coverage has different boundary edges')
        ring_area = sum(length(cross(sub(p,points[0]),sub(points[i+1],points[0])))/2
                        for i,p in enumerate(points[1:-1],1))
        face_area = sum(length(cross(sub(positions[k[1]],positions[k[0]]),
                                    sub(positions[k[2]],positions[k[0]])))/2 for k in candidates)
        if abs(face_area-ring_area) > max(tolerance*tolerance, ring_area*1e-5):
            raise ValueError(f'Collision surface {si} render/collision areas differ')
        slot = surface['material']
        shader = shader_reference(collision_materials[slot]) if 0 <= slot < len(collision_materials) else None
        if not shader or any(material_shaders.get(triangles[groups[k][0]]['material']) != shader for k in candidates):
            raise ValueError(f'Collision surface {si} lacks matching render/collision shader identity')
        rings.append(dict(source_surface=si, source_plane=surface['plane'], source_ring=ring,
            matched_position_ids=ring_ids, render_triangles=sorted(t for k in candidates for t in groups[k]),
            unified_triangles=sorted(groups[k][0] for k in candidates), collision_material=slot,
            source_shader=shader, boundary_edges_match=True, area_error=abs(face_area-ring_area)))
    # Every geometric collision polygon must have exactly two opposite source
    # sides. Every unified triangle must be covered by those two sides only.
    ring_groups = defaultdict(list); coverage = Counter()
    for row in rings:
        ring_groups[tuple(sorted(row['matched_position_ids']))].append(row)
        coverage.update(row['unified_triangles'])
    for copies in ring_groups.values():
        if (len(copies) != 2 or cycle(copies[0]['matched_position_ids']) !=
            cycle(tuple(reversed(copies[1]['matched_position_ids'])))):
            raise ValueError('Collision ring does not have one opposite-facing source copy')
    retained = sorted(v[0] for v in groups.values())
    if set(coverage) != set(retained) or any(n != 2 for n in coverage.values()):
        raise ValueError('Some render faces are missing, multiply covered or unrelated to collision')
    return dict(status='PROVEN_LOCAL_GEOMETRIC_CORRESPONDENCE', local_units=units,
        tolerance_ass_units=tolerance, tolerance_policy='Eight float32 ULPs at local-coordinate magnitude; no render welding',
        maximum_vertex_error_ass_units=max_vertex_error, maximum_plane_error_ass_units=max_plane_error,
        render_triangle_count=len(triangles), collision_surface_count=len(surfaces),
        unique_collision_polygon_count=len(ring_groups), unified_triangle_count=len(retained),
        retained_render_triangles=retained, suppressed_opposite_render_triangles=sorted(v[1] for v in groups.values()),
        corner_attributes='Exact UV/color/weights equality; opposite normals verified',
        all_render_faces_covered=True, all_collision_rings_covered=True, rings=rings,
        unified_position_table=positions, render_vertex_position_ids=vertex_ids)


def plan(bsp, instance_plan, record):
    """Bind a geometry proof through the already validated instance transform plan."""
    definition = record['source_definition']
    a = bsp['environment_semantics']['authoring']; d = a['definitions'][definition]
    placements = [p for p in instance_plan['placements'] if p['source_definition'] == definition]
    if not placements or {p['source_index'] for p in placements} != set(record['affected_instances']):
        raise ValueError('Unified breakable placement accounting differs from the source contract')
    selected_surfaces = set(record['affected'])
    all_surfaces = {s['source_surface'] for s in d['collision_mesh']['source_surfaces']}
    if selected_surfaces != {s['source_surface'] for s in d['collision_mesh']['source_surfaces'] if number(s['flags']) & 8}:
        raise ValueError('Breakable face partition does not cover every source breakable surface')
    object_ids = {p['render_object'] for p in placements}
    if len(object_ids) != 1 or None in object_ids or any(p['collision_definition'] != definition for p in placements):
        raise ValueError('Missing or inconsistent validated render/collision definition linkage')
    objects = [o for o in bsp['objects'] if o['id'] in object_ids]
    if len(objects) != 1:
        raise ValueError('Validated instance render object is absent or ambiguous')
    render = objects[0]
    partition = None
    collision = d['collision_mesh']
    source_render = render
    if selected_surfaces != all_surfaces:
        glass_surfaces=[s for s in collision['source_surfaces'] if s['source_surface'] in selected_surfaces]
        solid_surfaces=[s for s in collision['source_surfaces'] if s['source_surface'] not in selected_surfaces]
        def shader(s):
            slot=s['material']
            if not 0<=slot<len(a['collision_materials']):
                raise ValueError('Mixed face partition has no explicit collision material')
            return shader_reference(a['collision_materials'][slot])
        glass_shaders={shader(s) for s in glass_surfaces}; solid_shaders={shader(s) for s in solid_surfaces}
        if None in glass_shaders or glass_shaders & solid_shaders:
            raise ValueError('Mixed face partition needs disjoint explicit render/collision shader identities')
        ids=[i for i,t in enumerate(render['triangles']) if bsp['materials'][t['material']].get('source_shader') in glass_shaders]
        other=sorted(set(range(len(render['triangles'])))-set(ids))
        if not ids or not other or any(number(s['flags']) & ~7 for s in solid_surfaces):
            raise ValueError('Mixed face partition is empty or contains unsupported solid flags')
        used=sorted({v for i in ids for v in render['triangles'][i]['vertices']})
        remap={v:i for i,v in enumerate(used)}
        render=deepcopy(render)
        render['vertices']=[source_render['vertices'][v] for v in used]
        render['triangles']=[dict(source_render['triangles'][i],vertices=[remap[v] for v in source_render['triangles'][i]['vertices']]) for i in ids]
        collision=dict(collision,source_surfaces=glass_surfaces)
        partition=dict(method='Disjoint source shader identities followed by complete local glass geometry proof',
            breakable_render_triangles=ids,solid_render_triangles=other,
            breakable_collision_surfaces=sorted(selected_surfaces),solid_collision_surfaces=sorted(all_surfaces-selected_surfaces),
            original_render_vertices=used,generated_instance_suffix='_breakable',
            source_geometry_preserved='Glass becomes a separate unified instance; original frame render and collision remain paired at the same source transform')
    result = prove(render, collision, {i:m.get('source_shader') for i,m in enumerate(bsp['materials'])},
                   a['collision_materials'], units=bsp['units'])
    if partition:
        ids=partition['breakable_render_triangles']
        for name in ('retained_render_triangles','suppressed_opposite_render_triangles'):
            result[name]=[ids[i] for i in result[name]]
        mapped=[-1]*len(source_render['vertices'])
        for original,position in zip(partition['original_render_vertices'],result['render_vertex_position_ids']):
            mapped[original]=position
        result['render_vertex_position_ids']=mapped
        result['partition']=partition
        result['coverage_scope']='Exact breakable partition; solid remainder preserved separately'
    result.update(source_definition=definition, source_render_mesh=d['mesh index'], source_render_object=source_render['id'],
        placements=placements, source_surface_mapping=d.get('surfaces'),
        source_triangle_mapping=d.get('surface to triangle mapping'),
        correspondence_basis='Local coordinates, source planes, ring boundary edges, exact render coverage and shader identity; compiled triangle offsets are audit evidence only',
        target=dict(construct='Unified native Reach scenario mesh; same mesh generates render and collision',
            face_mode='breakable', face_sides='two_sided', collision_proxy=False,
            preserve_render_corner_attributes=True, preserve_material=True, preserve_placement_matrix=True,
            topology='Use retained render triangles and their original loop attributes; share the exact position IDs, retain seams in loop UVs/normals',
            source_definition_collision='Replaced by this proven equivalent unified mesh, never exported as a separate breakable proxy',
            breakable_support='Rebuild Reach breakable surfaces/support through normal Tool compilation from unified source geometry',
            native_validation_required='Check compiled render/collision material and breakable surface membership for every placement before runtime acceptance'))
    return result

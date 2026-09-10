"""Restore H3 sky authoring attributes omitted by the pinned JMS bridge.

The source triangle walk is checked against the existing decoded mesh. No
geometry, shader, texture, light sample or compiled target resource is replaced.
"""
from copy import deepcopy
import math
from . import fixtures


def _vec(row, name):
    values = [float(v) for v in fixtures.field(row, name).split(',')]
    if not all(math.isfinite(v) for v in values):
        raise ValueError('Nonfinite sky attribute: ' + name)
    return values


def _index(row, name):
    return int(fixtures.field(row, name).rsplit(',', 1)[-1])


def _strip(indices):
    # Same H3 strip parity/degenerate handling as the pinned JMS decoder.
    for i in range(len(indices)-2):
        a, b, c = indices[i:i+3]
        if len({a,b,c}) != 3:
            continue
        yield (a,c,b) if i & 1 else (a,b,c)


def recover(mesh, root):
    """Return a checked copy with source colors and explicit sky draw groups."""
    meshes = fixtures.block(root, 'meshes')
    temporary = fixtures.block(root, 'per mesh temporary')
    if len(meshes) != len(temporary):
        raise ValueError('Sky mesh/raw-geometry count mismatch')
    if fixtures.block(root, 'instance placements'):
        raise ValueError('Sky attribute recovery needs an explicit instance-placement mapping')
    bounds = fixtures.block(root, 'compression info')
    if len(bounds) != 1:
        raise ValueError('Sky attribute recovery requires one verified compression domain')
    bound = bounds[0]
    positions = _vec(bound,'position bounds 0') + _vec(bound,'position bounds 1')
    uvbounds = _vec(bound,'texcoord bounds 0') + _vec(bound,'texcoord bounds 1')
    # Tool XML prints six significant digits. Bound checks account only for
    # this textual quantization; colors retain the authored linear RGB values.
    position_tolerance = max(1.0, max(abs(v) for v in positions))*0.000006
    uv_tolerance = max(1.0, max(abs(v) for v in uvbounds))*0.000006
    source_materials = fixtures.block(root, 'materials')
    result = deepcopy(mesh)
    groups, walked, cursor = [], set(), 0
    max_position_error = max_uv_error = 0.0
    for ri,region in enumerate(fixtures.block(root,'regions')):
        for permutation in fixtures.block(region,'permutations'):
            start, count = _index(permutation,'mesh index'), _index(permutation,'mesh count')
            for mi in range(start,start+count):
                if mi in walked:
                    raise ValueError('Sky mesh is reused across authored regions/permutations')
                if mi < 0 or mi >= len(meshes):
                    raise ValueError('Invalid source sky mesh index')
                walked.add(mi)
                source = meshes[mi]
                flags = _index(source,'mesh flags')
                if flags & ~3:
                    raise ValueError('Unmapped source sky mesh flags: '+str(flags))
                colored = bool(flags & 1)
                raw = fixtures.block(temporary[mi],'raw vertices')
                indices = [_index(row,'word') & 65535 for row in fixtures.block(temporary[mi],'raw indices')]
                group_start = cursor
                for part in fixtures.block(source,'parts'):
                    shader = fixtures.field(source_materials[_index(part,'render method index')],'render method').split(',')[0].replace('\\','/').rsplit('/',1)[-1]
                    label = fixtures.field(permutation,'name')+' '+fixtures.field(region,'name')
                    slots = [i for i,m in enumerate(mesh['materials']) if m['name']==shader and m['label']==f'({i+1}) {label}']
                    if len(slots) != 1:
                        raise ValueError('Ambiguous source sky material/region identity')
                    begin, length = _index(part,'index start') & 65535, _index(part,'index count') & 65535
                    if begin+length > len(indices):
                        raise ValueError('Source sky part exceeds its index buffer')
                    part_indices = indices[begin:begin+length]
                    kind = fixtures.field(source,'index buffer type')
                    if kind == 'triangle strip':
                        triangles = _strip(part_indices)
                    elif kind == 'triangle list' and length % 3 == 0:
                        triangles = (part_indices[i:i+3] for i in range(0,length,3))
                    else:
                        raise ValueError('Unmapped source sky index-buffer type')
                    for triangle in triangles:
                        if cursor >= len(mesh['triangles']):
                            raise ValueError('Source sky triangle count changed')
                        target = mesh['triangles'][cursor]
                        if target['material'] != slots[0]:
                            raise ValueError('Source sky triangle/material correspondence changed')
                        for raw_index, target_index in zip(triangle,target['vertices']):
                            vertex = raw[raw_index]
                            pos,uv = _vec(vertex,'position'),_vec(vertex,'texcoord')
                            pos = [positions[2*i]+v*(positions[2*i+1]-positions[2*i]) for i,v in enumerate(pos)]
                            uv = [uvbounds[2*i]+v*(uvbounds[2*i+1]-uvbounds[2*i]) for i,v in enumerate(uv)]
                            uv[1] = 1-uv[1]
                            current = result['vertices'][target_index]
                            pe = max(abs(a-b/100) for a,b in zip(pos,current['position']))
                            ue = max(abs(a-b) for a,b in zip(uv,current['uvs'][0]))
                            ne = max(abs(a-b) for a,b in zip(_vec(vertex,'normal'),current['normal']))
                            if pe > position_tolerance or ue > uv_tolerance or ne > 0.000006:
                                raise ValueError(f'Sky vertex correspondence failed at mesh {mi}, triangle {cursor}, vertex {raw_index}: {pe}/{ue}/{ne}')
                            max_position_error,max_uv_error = max(max_position_error,pe),max(max_uv_error,ue)
                            color = _vec(vertex,'vertex color') if colored else None
                            if color is not None and (len(color)!=3 or min(color)<0):
                                raise ValueError('Invalid authored sky vertex color on a color-enabled mesh')
                            current['color'] = color
                        cursor += 1
                groups.append(dict(source_mesh=mi,source_region=ri,region_name=fixtures.field(region,'name'),
                    permutation_name=fixtures.field(permutation,'name'),has_vertex_color=colored,
                    sort_by_region=bool(flags&2),triangle_start=group_start,triangle_count=cursor-group_start))
    if cursor != len(mesh['triangles']):
        raise ValueError('Not every decoded sky triangle has source attribute evidence')
    result['source_draw_groups'] = groups
    result['source_attribute_recovery'] = dict(strategy='H3 raw authored vertex colors -> Foundry color attribute -> GR2 DiffuseColor0',
        source_triangles=cursor,colored_vertices=sum(v['color'] is not None for v in result['vertices']),
        source_draw_groups=len(groups),maximum_position_error_world=max_position_error,
        maximum_uv_error=max_uv_error,geometry_unchanged=True,texture_and_light_samples_unchanged=True)
    return result


def draw_meshes(mesh):
    """Keep uncolored meshes uncolored, and retain authored sky region order."""
    for group in mesh.get('source_draw_groups',[]):
        triangles = mesh['triangles'][group['triangle_start']:group['triangle_start']+group['triangle_count']]
        vertices, remap, new_triangles = [], {}, []
        for triangle in triangles:
            indices=[]
            for i in triangle['vertices']:
                if i not in remap:
                    remap[i]=len(vertices);vertices.append(mesh['vertices'][i])
                indices.append(remap[i])
            new_triangles.append(dict(triangle,vertices=indices))
        if any((v.get('color') is not None)!=group['has_vertex_color'] for v in vertices):
            raise ValueError('Mixed authored color-presence within a source sky mesh')
        yield group, dict(vertices=vertices,triangles=new_triangles,materials=mesh['materials'],nodes=mesh['nodes'],markers=[])


def native_color_readback(source, target, groups):
    """Check authored RGB multisets after Tool's vertex reordering/welding.

    This supplements the per-corner geometry correspondence checked by recover.
    Reach Tool marks every sky mesh color-enabled, including uncolored input;
    record its defaults without claiming those are recovered H3 authoring.
    """
    src = fixtures.block(source, 'per mesh temporary')
    dst = fixtures.block(target, 'per mesh temporary')
    if len(src) != len(dst) or len(groups) != len(src):
        raise ValueError('Native sky mesh count changed during color export')
    rows = []
    for group, native in zip(groups, dst):
        original = src[group['source_mesh']]
        a = sorted(_vec(v, 'vertex color') for v in fixtures.block(original, 'raw vertices'))
        b = sorted(_vec(v, 'vertex color') for v in fixtures.block(native, 'raw vertices'))
        row = dict(source_mesh=group['source_mesh'], region=group['region_name'],
            source_colored=group['has_vertex_color'], source_vertices=len(a), native_vertices=len(b))
        if group['has_vertex_color']:
            if not a or len(a) != len(b) or any(len(c) != 3 for c in a+b):
                raise ValueError('Native authored sky color count differs')
            error = max(abs(x-y) for c,d in zip(a,b) for x,y in zip(c,d))
            if error > 1e-6:
                raise ValueError('Native authored sky colors differ: '+group['region_name'])
            row.update(maximum_rgb_error=error, status='AUTHORED_RGB_MULTISET_VERIFIED')
        else:
            row.update(status='NO_SOURCE_COLOR_ATTRIBUTE', native_tool_default_black=all(c == [0,0,0] for c in b))
        rows.append(row)
    return rows

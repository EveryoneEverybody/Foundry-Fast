"""Read-only source/authoring/native light comparison and spatial evidence.

This does not change the compiler's light mapping or interpret raw scenario
lightmap-scale zero as proof that a light contributes nothing at runtime.
"""
import base64
import math
import struct
from . import fixtures


def numbers(value):
    return [float(v) for v in value.split(',')] if isinstance(value, str) else list(value)


def equivalent(a, b):
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(equivalent(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isfinite(a) and math.isfinite(b) and abs(a-b) <= 1e-5*max(1, abs(a), abs(b))
    return a == b


def audit_static(source, authored, native):
    """Compare every row, retaining all raw fields and explicit Reach defaults."""
    result = dict(definitions=[], instances=[], errors=[], assumptions=[
        'Source and Reach intensity numbers are preserved; cross-engine photometric units are unverified.',
        'H3 has no generic instance bounce field: Reach bounce 1 is a target default.',
        'H3 has no hotspot falloff-speed field: Reach speed 1 is a target default.',
        'Basis X=forward/Z=up follows the Foundry writer/importer; no additional Euler conversion.',
        'Reach light-version flags are postprocess markers, separate from attenuation behavior.'])
    sd, si = source['light_definitions'], source['light_instances']
    nd, ni = native['light_definitions'], native['light_instances']
    if (len(sd), len(si)) != (len(nd), len(ni)) or (len(sd), len(si)) != (len(authored['definitions']), len(authored['instances'])):
        result['errors'].append('Source/authored/native definition or instance count differs')
    def compare(index, values, destination):
        checks = {k: equivalent(v['source_expected'], v['authored']) and equivalent(v['authored'], v['native'])
                  for k, v in values.items()}
        row = dict(index=index, fields=values, checks=checks, status='MATCH' if all(checks.values()) else 'MISMATCH')
        destination.append(row)
        result['errors'].extend(f'{index}: {k}' for k, ok in checks.items() if not ok)
        return row
    def triple(s, a, n):
        return dict(source_expected=s, authored=a, native=n)
    for index, (s, a, n) in enumerate(zip(sd, authored['definitions'], nd)):
        if int(s['flags']) & ~3 or a['flags'] & ~3:
            result['errors'].append(f'Definition {index}: unrecognized source attenuation flags')
        flags = {v.strip() for v in n['flags'].split(',')} - {'', 'light version 1'}
        v = {'type': triple(s['type'], ['omni', 'spot', 'directional'][a['type']], n['type']),
             'shape': triple(s['shape'], a['source_fields']['shape'], n['shape'])}
        for field, key in [('color', 'color'), ('near attenuation bounds', 'near_attenuation'), ('far attenuation bounds', 'far_attenuation')]:
            v[field] = triple(numbers(s[field]), a[key], numbers(n[field]))
        for field in ('intensity', 'aspect'):
            v[field] = triple(float(s[field]), a[field], float(n[field]))
        for field, source_field, key in [('hotspot size', 'hotspot size', 'hotspot_size'),
                ('hotspot cutoff size', 'hotspot falloff size', 'hotspot_cutoff')]:
            v[field] = triple(math.degrees(float(s[source_field])), a[key], float(n[field]))
        v['hotspot falloff speed'] = triple(1., a['hotspot_falloff'], float(n['hotspot falloff speed']))
        expected_flags = {name for bit, name in [(1, 'use near attenuation'), (2, 'use far attenuation')] if int(s['flags']) & bit}
        authored_flags = {name for bit, name in [(1, 'use near attenuation'), (2, 'use far attenuation')] if a['flags'] & bit}
        v['attenuation flags'] = triple(sorted(expected_flags), sorted(authored_flags), sorted(flags))
        row = compare(index, v, result['definitions'])
        row['fields']['hotspot falloff speed']['origin'] = 'Reach default; absent in H3 source definition'
        row.update(source_raw=s, authored_raw=a, native_raw=n)
    for index, (s, a, n) in enumerate(zip(si, authored['instances'], ni)):
        v = {'definition index': triple(int(s['definition index']), a['definition_index'], int(n['definition index']))}
        for key in ('origin', 'forward', 'up'):
            v[key] = triple(numbers(s[key]), a[key], numbers(n[key]))
        for key, default in [('bounce light control', 1), ('light volume distance', 0), ('light volume intensity scalar', 0),
                             ('fade out distance', 0), ('fade start distance', 0), ('shader reference index', -1)]:
            v[key] = triple(default, default, float(n[key]))
        v['bungie light type'] = triple('default ligthmap light', 'default ligthmap light', n['bungie light type'])
        for key in ('user control', 'shader reference', 'gel reference', 'lens flare reference'):
            v[key] = triple('', '', n[key])
        v['screen space specular'] = triple('', '', ','.join(sorted(set(n['screen space specular'].split(',')) - {'version 1 instances', ''})))
        row = compare(index, v, result['instances'])
        for key in v.keys() - {'definition index', 'origin', 'forward', 'up'}:
            row['fields'][key]['origin'] = 'Reach default; absent in H3 generic instance'
        row.update(source_raw=s, authored_raw=a, native_raw=n,
                   definition_status=result['definitions'][a['definition_index']]['status'])
    result['status'] = 'STRUCTURAL_MATCH' if not result['errors'] else 'MISMATCH'
    return result


def assert_intensity_delta(baseline, actual, factor):
    """A diagnostic may change power only, including no emissive/material drift."""
    from copy import deepcopy
    expected = deepcopy(baseline)
    for row in expected['light_definitions']:
        row['intensity'] = str(float(row['intensity'])*factor)
    for block in ('light_definitions', 'light_instances', 'materials'):
        if len(expected[block]) != len(actual[block]):
            raise ValueError('Diagnostic changed '+block+' count')
        for index, (a, b) in enumerate(zip(expected[block], actual[block])):
            if set(a) != set(b): raise ValueError('Diagnostic changed field set')
            for key in a:
                try: equal = equivalent(numbers(a[key]), numbers(b[key]))
                except (ValueError, TypeError): equal = a[key] == b[key]
                if not equal: raise ValueError(f'Diagnostic changed {block}[{index}].{key}')


def scenario_placements(root):
    """Keep duplicate displayed fields ordered; palette type is a block index."""
    rows = []
    for index, node in enumerate(fixtures.block(root, 'light volumes')):
        fields = [dict(e.attrib) for e in node if e.tag == 'field']
        palette = [e for e in fields if e['name'] == 'type' and e['type'] == 'short block index']
        shape = [e for e in fields if e['name'] == 'type' and e['type'] == 'short enum']
        if len(palette) != 1 or len(shape) != 1:
            raise ValueError('Ambiguous light palette identity/volume shape')
        rows.append(dict(index=index, palette_index=int(palette[0]['value'].rsplit(',', 1)[-1]), volume_shape=shape[0]['value'],
            position=numbers(fixtures.field(node, 'position')), rotation_degrees=numbers(fixtures.field(node, 'rotation')),
            ordered_source_fields=fields, membership_policy='Resolve geometrically; do not infer from palette index',
            lightmap_scale_interpretation='Raw value retained; zero/default engine semantics not established'))
    return rows


def compare_split_lights(scenario, resource):
    """Resource rows are compared as ordered fields, never added as duplicates."""
    def rows(root, name):
        return [[dict(f.attrib) for f in e if f.tag == 'field'] for e in fixtures.block(root, name)]
    embedded, split = rows(scenario, 'light volumes'), rows(resource, 'lights')
    palettes = rows(scenario, 'light volumes palette') == rows(resource, 'light palette')
    return dict(embedded_count=len(embedded), resource_count=len(split), ordered_fields_match=embedded == split,
                palette_match=palettes, status='IDENTICAL_SPLIT_COPY' if embedded == split and palettes else 'NEEDS_RECONCILIATION')


def constant_function(encoded):
    """Only non-ranged type-1 constants; pinned blam-tags header semantics."""
    encoded = encoded.split(',', 1)[-1]
    data = base64.b64decode(encoded + '='*((-len(encoded)) % 4), validate=True)
    if len(data) != 32 or data[0] != 1 or data[1] & 1:
        raise ValueError('Not a verified non-ranged constant function')
    if data[2]:
        argb = struct.unpack_from('<I', data, 4)[0]
        value = [(argb >> shift & 255)/255 for shift in (16, 8, 0)]
    else:
        value = struct.unpack_from('<f', data, 4)[0]
        if not math.isfinite(value):
            raise ValueError('Nonfinite light function')
    return dict(value=value, convention='Authored non-ranged constant, independent of time/input',
                header_hex=data.hex(), color=bool(data[2]), evidence='blam-tags tag_function: color_count/as_constant')


def locate_point(tree, point, epsilon=1e-6):
    """Packed H3 BSP query. On a splitting plane, visit both sides conservatively.

    blam-tags collision_verify children/descend_point: n.dot(p)-d >= 0 -> front.
    A valid leaf cluster establishes spatial membership, not light-volume policy.
    """
    if tree.get('unsupported_supernodes', 0):
        raise ValueError('Reach supernode traversal is not implemented; native membership is unverified')
    stack, leaves, solid, boundary = [(0, frozenset())], set(), False, False
    visited_count = 0
    while stack:
        child, seen = stack.pop()
        if child == 0xffffff:
            solid = True
            continue
        if child & 0x800000:
            index = child & 0x7fffff
            if index >= len(tree['leaf_clusters']):
                raise ValueError('Out-of-range collision leaf')
            leaves.add(index)
            continue
        if child in seen or child >= len(tree['nodes_u64']):
            raise ValueError('Cyclic or invalid collision node')
        visited_count += 1
        if visited_count > len(tree['nodes_u64'])*2:
            raise ValueError('Ambiguous collision query exceeds traversal budget')
        packed = int(tree['nodes_u64'][child])
        pi = packed & 0xffff
        if pi >= len(tree['planes']):
            raise ValueError('Invalid collision plane')
        plane = tree['planes'][pi]
        distance = sum(a*b for a, b in zip(plane[:3], point))-plane[3]
        if not math.isfinite(distance):
            raise ValueError('Nonfinite collision query')
        back, front = (packed >> 16) & 0xffffff, (packed >> 40) & 0xffffff
        next_seen = seen | {child}
        if abs(distance) <= epsilon:
            boundary = True
            stack.extend([(back, next_seen), (front, next_seen)])
        else:
            stack.append((front if distance > 0 else back, next_seen))
    clusters = sorted({tree['leaf_clusters'][i] for i in leaves if tree['leaf_clusters'][i] >= 0})
    return dict(leaf_indices=sorted(leaves), clusters=clusters, solid_branch=solid, near_partition=boundary,
                status='INSIDE_BSP_CLUSTER' if clusters and not solid else 'BOUNDARY_OR_OUTSIDE', nodes_visited=visited_count)


def closest_triangle(point, a, b, c):
    """Closest point on a closed triangle, including edge and vertex regions."""
    def sub(x, y): return tuple(u-v for u, v in zip(x, y))
    def dot(x, y): return sum(u*v for u, v in zip(x, y))
    def lerp(x, y, t): return tuple(u+(v-u)*t for u, v in zip(x, y))
    ab, ac, ap = sub(b, a), sub(c, a), sub(point, a)
    d1, d2 = dot(ab, ap), dot(ac, ap)
    bp = sub(point, b); d3, d4 = dot(ab, bp), dot(ac, bp)
    cp = sub(point, c); d5, d6 = dot(ab, cp), dot(ac, cp)
    cross = (ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0])
    if dot(cross, cross) <= 1e-20:
        candidates = []
        for x, y in ((a, b), (b, c), (c, a)):
            edge = sub(y, x); length = dot(edge, edge)
            candidates.append(lerp(x, y, min(1, max(0, dot(sub(point, x), edge)/length))) if length else x)
        return min(candidates, key=lambda p: dot(sub(p, point), sub(p, point)))
    if d1 <= 0 and d2 <= 0: return a
    if d3 >= 0 and d4 <= d3: return b
    vc = d1*d4-d3*d2
    if vc <= 0 and d1 >= 0 and d3 <= 0: return lerp(a, b, d1/(d1-d3))
    if d6 >= 0 and d5 <= d6: return c
    vb = d5*d2-d1*d6
    if vb <= 0 and d2 >= 0 and d6 <= 0: return lerp(a, c, d2/(d2-d6))
    va = d3*d6-d5*d4
    if va <= 0 and d4-d3 >= 0 and d5-d6 >= 0: return lerp(b, c, (d4-d3)/((d4-d3)+(d5-d6)))
    v, w = vb/(va+vb+vc), vc/(va+vb+vc)
    return tuple(a[i]+ab[i]*v+ac[i]*w for i in range(3))

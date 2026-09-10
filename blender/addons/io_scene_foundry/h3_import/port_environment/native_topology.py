"""Recover authoring polygons from compiled collision rings, without new closure."""
from copy import deepcopy
from collections import Counter
import math
from .authoring import number


def boundary(triangles):
    edges=Counter((a,b) for t in triangles for a,b in zip(t['vertices'],t['vertices'][1:]+t['vertices'][:1]))
    remaining=[e for e,count in edges.items() if count-edges.get((e[1],e[0]),0)==1]
    following=dict(remaining)
    if not remaining or len(following)!=len(remaining):
        raise ValueError('Collision surface has no unique directed boundary')
    start=remaining[0][0];ring=[start]
    while following[ring[-1]]!=start:
        vertex=following[ring[-1]]
        if vertex in ring or vertex not in following:raise ValueError('Collision boundary is not one closed ring')
        ring.append(vertex)
    if len(ring)!=len(remaining):raise ValueError('Collision surface contains disconnected boundaries')
    return ring


def canonical_cycle(values):
    values=tuple(values)
    return min(values[i:]+values[:i] for i in range(len(values)))


def collision_polygons(record, surfaces, label):
    """A compiled two-sided front/back pair becomes one native two-sided face.

    Require exact positions, reverse cyclic order, source material and flags.
    Never merge unrelated coplanar polygons or infer adjacency from a plane.
    """
    result=deepcopy(record);polygons=[];kept=[];seen={};pairs=[]
    for surface in surfaces:
        start=surface['triangle_start'];count=surface['triangle_count']
        triangles=record['triangles'][start:start+count]
        if not triangles:continue
        ring=surface.get('ring',{}).get('decoded_vertices') or boundary(triangles)
        positions=[tuple(record['vertices'][i]['position']) for i in ring]
        flags=int(number(surface['flags']))
        key=(surface['material'],flags,canonical_cycle(positions))
        opposite=(surface['material'],flags,canonical_cycle(list(reversed(positions))))
        if flags & 1 and opposite in seen:
            pairs.append([seen[opposite],surface['source_surface']])
            continue
        if key in seen:
            raise ValueError('Repeated collision polygon with equal winding: '+label)
        seen[key]=surface['source_surface']
        face=deepcopy(triangles[0]);face['vertices']=ring
        polygons.append(face)
        new=deepcopy(surface);new.update(triangle_start=len(polygons)-1,triangle_count=1)
        kept.append(new)
    result['triangles']=polygons;result['source_surfaces']=kept
    result['native_topology']=dict(source=label,source_surfaces=len(surfaces),authored_polygons=len(polygons),
        paired_two_sided_surfaces=pairs,strategy='Exact source-ring boundary; reversed coincident two-sided pairs authored once')
    return result


def render_slivers(record, label):
    """Remove only sub-resolution render-only triangles; collision is separate.

    The bound is one millionth of a square world unit. Retain every removed
    source face in the build report; never apply this to unified breakability.
    """
    if record.get('face_mode')!='render_only':return record
    kept=[];removed=[]
    for index,face in enumerate(record['triangles']):
        a,b,c=[record['vertices'][i]['position'] for i in face['vertices']]
        u=[(b[i]-a[i])/100 for i in range(3)];v=[(c[i]-a[i])/100 for i in range(3)]
        cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
        area=math.sqrt(sum(x*x for x in cross))/2
        longest=max(math.dist(a,b),math.dist(b,c),math.dist(c,a))/100
        altitude=2*area/longest if longest else 0
        # Long slivers can exceed the area bound while their width lies below
        # world float32 precision. The real Tool-rejected outer-panel triangle
        # has altitude 1.34214e-5 and area 2.05236e-5 world units squared.
        if area<=1e-6 or (altitude<2e-5 and area<1e-4):
            removed.append(dict(source_face=index,area_world_squared=area,minimum_altitude_world=altitude,face=deepcopy(face)))
        else:kept.append(face)
    record['triangles']=kept
    record['render_slivers']=dict(source=label,removed=removed,area_threshold_world_squared=1e-6,
        narrow_sliver_limits=dict(altitude_world=2e-5,area_world_squared=1e-4),
        collision='Unchanged source collision; this pass is restricted to render-only geometry')
    return record

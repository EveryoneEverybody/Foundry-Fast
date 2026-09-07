"""Zone membership and the extant collision of an inactive source seam.

H3 and Reach runtime evidence establish that a seam requires two connected BSP
owners. H3 keeps its seam collision material extant while the neighbor is absent.
The static slice therefore retains the exact source collision face. It must not
emit a Reach IsSeam material with no mapping: Reach treats that case differently.
"""
from collections import Counter
from copy import deepcopy
import math

from . import authoring, fixtures
from .breakable_geometry import edges, cross, sub, length
from .selection import index


def discover_neighbors(scenario_xml, bsps, seams_xml, export_metadata):
    """Read only candidate BSP seam metadata, never extract their environment."""
    seams, _ = authoring.seam_plan(seams_xml, bsps)
    selected = {b['bsp_index'] for b in bsps}
    pending = {s['source_index']:s for s in seams if len(s['owners']) == 1}
    sources = fixtures.block(scenario_xml, 'structure bsps')
    zones = [dict(name=fixtures.field(z,'name'), bsp_mask=int(fixtures.field(z,'bsp zone flags')))
             for z in fixtures.block(scenario_xml,'zone sets')]
    result = dict(source_zone_sets=zones, neighbor_evidence=[], inspected_source_bsps=[], selected_indices=sorted(selected))
    def priority(i):
        masks = [z['bsp_mask'] for z in zones if z['bsp_mask'] & (1 << i) and
                 any(z['bsp_mask'] & (1 << s['owners'][0]['source_bsp_index']) for s in pending.values())]
        return (min((m.bit_count() for m in masks), default=33), i)
    for i in sorted(set(range(len(sources)))-selected, key=priority):
        if not pending: break
        source = fixtures.reference(sources[i], 'structure bsp', 'scenario_structure_bsp')
        root, provenance = export_metadata(i, source)
        if root.get('id','').replace('\\','/')+'.scenario_structure_bsp' != source:
            raise ValueError('Seam evidence BSP identity differs from source scenario')
        result['inspected_source_bsps'].append(dict(source_bsp_index=i, source_bsp=source, **provenance))
        for si, row in enumerate(fixtures.block(root,'seam identifiers')):
            seam = pending.get(si)
            if seam is None: continue
            identifier = [int(fixtures.field(row,f'seam_id{k}')) for k in range(4)]
            clusters = fixtures.block(row,'cluster mapping'); edge_map = fixtures.block(row,'edge mapping')
            if (identifier != seam['identifier'] or not clusters or not edge_map
                or any(int(fixtures.field(e,'structure edge index')) < 0 for e in edge_map)): continue
            centers = [authoring.vector(fixtures.field(c,'cluster center')) for c in clusters]
            expected = [c['cluster center']['values'] for c in seam['owners'][0]['cluster_mapping']]
            if len(centers) != len(expected) or any(min(math.dist(c,e) for e in expected) > 1e-4 for c in centers):
                continue  # Repeated identifiers alone never create adjacency.
            result['neighbor_evidence'].append(dict(source_seam_index=si, identifier=identifier,
                selected_owner=seam['owners'][0], inactive_neighbor=dict(source_bsp_index=i, source_bsp=source,
                    source_clusters=[dict(source_index=index(fixtures.field(c,'cluster_index')),
                                          center=authoring.vector(fixtures.field(c,'cluster center'))) for c in clusters],
                    source_edge_mapping=[fixtures.fields(e) for e in edge_map], **provenance),
                relationship='Same global seam table index + identifier + nonempty cluster/edge mapping + coincident cluster centers',
                geometry_scope='Neighbor seam metadata only; no neighbor render/collision/material build'))
            del pending[si]
    result['unresolved_neighbors'] = sorted(pending)
    return result


def collision_boundary(seam, bsp):
    sem = bsp['environment_semantics']; a = sem['authoring']
    slots = {i for i,m in enumerate(a['collision_materials']) if m['seam mapping index'] == seam['source_index']}
    surfaces = [s for s in sem['collision_surfaces'] if s['material'] in slots]
    if not surfaces or any(authoring.number(s['flags']) for s in surfaces):
        raise ValueError('Inactive seam needs decoded ordinary source collision surfaces')
    obj = next(o for o in bsp['objects'] if o['id'] == sem['collision_object'])
    reference = seam['vertices_world']; triangle_ids=[]; mapped=[]; maximum_error=0.0
    tolerance=1e-4  # H3 Tool XML prints world coordinates at six significant decimals.
    for s in surfaces:
        for ti in range(s['triangle_start'],s['triangle_start']+s['triangle_count']):
            if ti < 0 or ti >= len(obj['triangles']): raise ValueError('Invalid seam collision triangle range')
            ids=[]
            for vi in obj['triangles'][ti]['vertices']:
                position=[v/100 for v in obj['vertices'][vi]['position']]
                candidates=[(math.dist(position,p),i) for i,p in enumerate(reference) if math.dist(position,p) <= tolerance]
                if len(candidates)!=1: raise ValueError('Seam collision vertex has no unique global seam correspondence')
                error,i=candidates[0];maximum_error=max(maximum_error,error);ids.append(i)
            if len(set(ids))!=3: raise ValueError('Degenerate source seam collision triangle')
            triangle_ids.append(ti);mapped.append(ids)
    def boundary(triangles):
        counts=Counter(e for t in triangles for e in edges(t))
        if any(n not in (1,2) for n in counts.values()): raise ValueError('Overlapping seam topology')
        return {e for e,n in counts.items() if n==1}
    def area(triangles):
        return sum(length(cross(sub(reference[t[1]],reference[t[0]]),sub(reference[t[2]],reference[t[0]])))/2 for t in triangles)
    if boundary(mapped)!=boundary(seam['triangles']) or not math.isclose(area(mapped),area(seam['triangles']),rel_tol=1e-8,abs_tol=1e-10):
        raise ValueError('Source collision does not cover the exact global seam boundary')
    return dict(source_bsp=bsp['source_tag'], source_bsp_index=bsp['bsp_index'],
        source_collision_object=obj['id'], source_collision_surfaces=surfaces, source_collision_triangle_indices=triangle_ids,
        source_collision_materials=[dict(slot=i,record=a['collision_materials'][i]) for i in sorted(slots)],
        source_collision_vertices_world=[[v/100 for v in obj['vertices'][vi]['position']]
                                         for ti in triangle_ids for vi in obj['triangles'][ti]['vertices']],
        global_seam_vertex_indices=mapped, maximum_vertex_error_world=maximum_error,
        tolerance_world=tolerance, boundary_edges_match=True, area_match=True,
        preserve_source_triangle_winding=True)


def plan(record, environment, bsps):
    if len(record['affected']) != 1: raise ValueError('Expected one source seam observation')
    si=record['affected'][0]
    seam=next(s for s in environment['seams'] if s['source_index']==si)
    if len(seam['owners'])!=1: raise ValueError('Inactive-neighbor rule requires exactly one selected owner')
    owner=seam['owners'][0];selected={b['bsp_index'] for b in bsps}
    if selected!={b['source_index'] for b in environment['selection']['bsps']} or owner['source_bsp_index'] not in selected:
        raise ValueError('Selected BSP decode is incomplete; cannot infer an absent neighbor')
    context=environment.get('seam_source_context',{})
    neighbor=next(e for e in context.get('neighbor_evidence',[]) if e['source_seam_index']==si)
    if neighbor['identifier']!=seam['identifier'] or neighbor['selected_owner']!=owner:
        raise ValueError('Inactive-neighbor evidence does not match global seam identity/owner')
    other=neighbor['inactive_neighbor']['source_bsp_index']
    if other in selected: raise ValueError('Source neighbor is selected; this seam must be paired')
    pair_mask=(1<<other)|(1<<owner['source_bsp_index'])
    states=[dict(z, seam_active=(z['bsp_mask'] & pair_mask)==pair_mask,
        selected_owner_present=bool(z['bsp_mask'] & (1<<owner['source_bsp_index']))) for z in context['source_zone_sets']]
    collision=collision_boundary(seam,next(b for b in bsps if b['bsp_index']==owner['source_bsp_index']))
    return dict(source_seam=deepcopy(seam), source_neighbor_evidence=neighbor, source_zone_states=states,
        selected_state='INACTIVE_NEIGHBOR_ABSENT', selected_seam_active=False,
        source_collision_extant=True, collision_correspondence=collision,
        activation_predicate='Both BSP owners connected; one absent owner disables the seam connection',
        target=dict(selected_slice='Retain the existing source seam collision triangles as native collision-only faces',
            face_mode='collision_only', face_type='normal', seam_connector=False, added_geometry=False,
            collision_source='Exact source collision object/triangles in collision_correspondence; not a generated closure',
            visibility='No connected neighbor cluster; retained collision faces do not render',
            future_zone_sets='Retain original seam geometry/identity; when both BSPs are selected, replace this static boundary state with the native paired seam authoring path',
            reach_unmapped_seam_caveat='Do not emit IsSeam with mapping -1: Reach excludes that material from extant collision, unlike this H3 inactive mapped seam',
            native_validation_required='Verify retained source boundary collision and absence of an active neighbor connection; paired seams still require native Tool validation'),
        native_writes=False)

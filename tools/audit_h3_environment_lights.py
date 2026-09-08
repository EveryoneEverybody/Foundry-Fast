"""Audit an accepted environment's lighting using source/native read-only exports.

python tools/audit_h3_environment_lights.py --config <audit-config.json>
Output is restricted to a new report folder outside both kits.
"""
import argparse
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment import fixtures, lighting_audit as audit
from port_environment.paths import OutputPaths, Ownership, digest, atomic_json


def emissive_groups(bsp, geometry):
    materials = {m['slot']: m for m in bsp['materials'] if float(m.get('lighting', {}).get('emissive power', 0)) > 0}
    objects = {o['id']: o for o in geometry['objects']}
    groups = []
    def add(obj, identity, matrix):
        triangles = {}
        for ti, t in enumerate(obj['triangles']):
            if t['material'] not in materials:
                continue
            vertices = []
            for vi in t['vertices']:
                p = obj['vertices'][vi]['position']
                vertices.append(tuple((sum(matrix[i][j]*p[j] for j in range(3))+matrix[i][3])/100 for i in range(3)))
            triangles.setdefault(t['material'], []).append((ti, vertices))
        for slot, rows in triangles.items():
            coords = [v for _, vs in rows for v in vs]
            groups.append(dict(**identity, source_render_object=obj['id'], material_slot=slot,
                source_shader=materials[slot]['source_shader'], source_emissive=materials[slot]['lighting'],
                triangles=rows, bounds=[[min(p[i] for p in coords), max(p[i] for p in coords)] for i in range(3)]))
    identity = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    for mesh in bsp['meshes']:
        if mesh['role'] != 'render': continue
        t = mesh['source_transform']
        if t['position'] != [0, 0, 0] or t['rotation'] != [1, 0, 0, 0] or t['scale'] != 1:
            raise ValueError('Base mesh audit needs a decoded world transform')
        add(objects[mesh['id']], dict(name=mesh['name'], source_placement=None, role='base_cluster'), identity)
    for p in bsp['instance_plan']['placements']:
        if p.get('render_object') is not None:
            add(objects[p['render_object']], dict(name=p['name'], source_placement=p['source_index'],
                source_definition=p['source_definition'], role='bsp_instance'), p['matrix'])
    return groups


def nearest(point, groups, count=3):
    candidates = []
    for g in groups:
        bound_distance = sum(max(lo-p, 0, p-hi)**2 for p, (lo, hi) in zip(point, g['bounds']))
        if len(candidates) >= count and bound_distance > candidates[-1]['distance_world']**2:
            continue
        best = None
        for ti, vertices in g['triangles']:
            closest = audit.closest_triangle(point, *vertices)
            distance = math.dist(point, closest)
            if best is None or distance < best[0]: best = (distance, ti, closest)
        row = {k: v for k, v in g.items() if k != 'triangles'}
        row.update(distance_world=best[0], triangle_index=best[1], nearest_point_world=best[2],
            inference='Spatial proximity only; does not prove the light belongs to this fixture')
        candidates.append(row)
        candidates.sort(key=lambda v: (v['distance_world'], v['name'], v['material_slot']))
        candidates = candidates[:count]
    return candidates


def main(c):
    paths = OutputPaths(c['h3_root'], c['reach_root'], c['namespace'], allow_nested=True)
    out = Path(c['output']).resolve()
    Ownership(paths, out)
    if out.exists(): raise ValueError('Use a new report folder')
    plan = json.loads(Path(c['accepted_plan']).read_text())
    bsp_index = c['bsp_index']; bsp = plan['bsps'][bsp_index]
    source_dir = Path(c['source_run'])
    source = fixtures.lighting_semantics(fixtures.parse((source_dir/f'lighting-{bsp_index}.xml').read_bytes()))
    native = fixtures.lighting_semantics(fixtures.parse(Path(c['native_lighting_xml']).read_bytes()))
    result = audit.audit_static(source, plan['lighting_by_bsp'][bsp_index], native)
    tree = json.loads(Path(c['spatial_tree']).read_text(encoding='utf-8-sig'))
    if digest(paths.source(bsp['source_tag'])) != tree['source_sha256']:
        raise ValueError('Collision tree source changed')
    geometry = json.loads((source_dir/'source'/bsp['geometry_source']['file']).read_text())
    groups = emissive_groups(bsp, geometry)
    for row in result['instances']:
        point = row['authored_raw']['origin']
        row.update(spatial_membership=audit.locate_point(tree, point), nearest_emissive_geometry=nearest(point, groups))
    root = fixtures.read_authoring(source_dir/'scenario.xml', {'light volumes', 'light volumes palette', 'scenario resources'})
    resources = dict(references=[e.attrib for e in root.iter('field') if e.get('name') in ('light resource', 'structure lighting resource')],
                     status='NOT_CHECKED')
    if c.get('scenario_lights_resource_xml'):
        resource_path = Path(c['scenario_lights_resource_xml'])
        resource = fixtures.parse(resource_path.read_bytes())
        identities = [e['value'].split(',')[0].replace('\\','/') for e in resources['references'] if e['name']=='light resource']
        if identities != [resource.get('id').replace('\\','/')]:
            raise ValueError('Split light resource identity does not match scenario reference')
        resources.update(audit.compare_split_lights(root, resource), source_xml_sha256=digest(resource_path))
        resources['source_tag_sha256'] = digest(paths.source(identities[0]+'.scenario_lights_resource'))
    if c.get('structure_lights_resource_xml'):
        structure_path=Path(c['structure_lights_resource_xml'])
        structure=fixtures.parse(structure_path.read_bytes())
        resources['structure_resource'] = dict(source_xml_sha256=digest(structure_path), exported_root_fields=len(list(structure)),
            source_tag_sha256=digest(paths.source(structure.get('id')+'.scenario_structure_lighting_resource')),
            interpretation='No authored root fields exposed; pinned H3 schema declares padding only')
    placements = audit.scenario_placements(root)
    palette = []
    for index, e in enumerate(fixtures.block(root, 'light volumes palette')):
        path = fixtures.reference(e, 'name', 'light')
        xml = source_dir/f'light-tag-{index}.xml'
        tag = fixtures.parse(xml.read_bytes())
        functions = [audit.constant_function(e.get('value')) for e in tag if e.get('type') == 'data']
        if len(functions) != 2: raise ValueError('Expected color and intensity functions')
        palette.append(dict(index=index, source_tag=path, source_sha256=digest(paths.source(path)),
            source_xml_sha256=digest(xml), source_fields=fixtures.fields(tag),
            color=functions[0], intensity=functions[1],
            placement_indices=[r['index'] for r in placements if r['palette_index'] == index]))
    for r in placements:
        r.update(spatial_membership=audit.locate_point(tree, r['position']),
                 nearest_emissive_geometry=nearest(r['position'], groups),
                 classification='OMITTED_BOUND_SCENARIO_LIGHT' if r['palette_index'] >= 0 else 'UNBOUND_SOURCE_PLACEMENT',
                 native_placement_written=False)
        if r['palette_index'] >= len(palette): raise ValueError('Invalid palette reference')
    report = dict(format='foundry.h3-environment.light-audit', version=1, static_lights=result,
        source_scenario_placements=placements, source_light_palette=palette, split_resource_audit=resources,
        emissive_geometry_inventory=[{**{k:v for k,v in g.items() if k!='triangles'}, 'triangle_count':len(g['triangles'])} for g in groups],
        provenance=dict(config=c, accepted_plan_sha256=digest(c['accepted_plan']), plan_internal_sha256=plan['plan_sha256'],
            source_bsp_sha256=tree['source_sha256'], native_lighting_xml_sha256=digest(c['native_lighting_xml']),
            source_lighting_xml_sha256=digest(source_dir/f'lighting-{bsp_index}.xml'),
            source_scenario_xml_sha256=digest(source_dir/'scenario.xml'),
            source_geometry_sha256=digest(source_dir/'source'/bsp['geometry_source']['file']),
            source_snapshot_validation=plan.get('source_validation_basis'),
            source_tree_decoder=tree['decoder']),
        reach_content_written=False, photometric_equivalence='UNVERIFIED',
        conclusions=[
            'Readback equality establishes field preservation, not equivalent photometric response.',
            'Scenario light-volume membership is queried from source collision leaves, not guessed from bounds.',
            'Nearest emissive source geometry is an association candidate, not an authored ownership relationship.',
            'Raw zero lightmap scale does not establish absence of runtime light; its default semantics remain unverified.',
            'Bound scenario lights remain omitted by the environment scope; unused palette entries are not placements.'])
    out.mkdir(parents=True)
    atomic_json(out/'bsp010-light-audit.json', report)
    text = ['# BSP010 source / authored / native light audit', '',
        f"Static result: **{result['status']}**, {len(result['instances'])} instances, {len(result['definitions'])} definitions.", '',
        'The JSON records every compared field at all three stages, original raw rows, spatial queries and nearest source triangles.', '',
        '| Definition | Shape | Source = native power | RGB | Inner / outer degrees | Near / far WU | Enabled attenuation |',
        '|---|---|---:|---|---|---|---|']
    for d in result['definitions']:
        a = d['authored_raw']
        text.append(f"| {d['index']} | {a['source_fields']['shape']} | {a['intensity']:g} | {a['color']} | {a['hotspot_size']:.4f} / {a['hotspot_cutoff']:.4f} | {a['near_attenuation']} / {a['far_attenuation']} | {d['fields']['attenuation flags']['native']} |")
    text += ['', 'All are spots. Far bounds on definitions 0 and 1 are stored but disabled. Definition 2 alone enables far attenuation. Bounce 1 and hotspot falloff speed 1 are Reach defaults, not H3 source fields.', '',
        '| Instance | Def | Source = native position WU | Cluster | Nearest emissive source mesh | Distance WU | Result |', '|---|---|---|---|---|---:|---|']
    for r in result['instances']:
        a=r['authored_raw'];n=r['nearest_emissive_geometry'][0]
        text.append(f"| {r['index']} | {a['definition_index']} | {a['origin']} | {r['spatial_membership']['clusters']} | {n['name']} / placement {n['source_placement']} | {n['distance_world']:.4f} | {r['status']} |")
    text += ['', 'Forward/up are preserved directly in every row; native bounce is 1, default lightmap type, empty light/shader/gel references, and no fade or volume override. No viewport-light inference is used.', '',
        '| Omitted source row | Palette | Source position WU | Cluster | Nearest emissive source mesh | Distance WU |', '|---|---|---|---|---|---:|']
    for r in placements:
        n=r['nearest_emissive_geometry'][0]
        text.append(f"| {r['index']} | {r['palette_index']} | {r['position']} | {r['spatial_membership']['clusters']} | {n['name']} / placement {n['source_placement']} | {n['distance_world']:.4f} |")
    text += ['', 'Palette inventory:', '']
    for p in palette:
        text.append(f"- {p['index']}: `{p['source_tag']}`; bound rows {p['placement_indices']}; constant intensity {p['intensity']['value']}; RGB {p['color']['value']}.")
    text += ['', f"Split resource audit: **{resources['status']}**. Identical split copies are not counted as additional placements.", '',
        'The table measures proximity to source surfaces with positive emissive authoring. A nearby fixture is a candidate association; a distant nearest triangle does not establish fixture ownership. Unbound rows have no light tag. Shape and distance overrides are retained in JSON; precedence over tag fields has not been established.', '',
        'No scenario light was authored by this audit. Zero lightmap scale is retained without claiming it proves zero runtime contribution. No constant-function sampling or wall-clock state was used.', '',
        'Evidence: [Reach light authoring parameters](https://c20.reclaimers.net/hr/guides/json-parameters/), [H3 baked lighting](https://c20.reclaimers.net/h3/guides/map-making/baked-lighting), pinned blam-tags collision_verify::children/descend_point and tag_function::color_count/as_constant, Foundry native_scene::write_static_lights and ScenarioStructureLightingInfoTag build/write/read methods.', '',
        'This audit does not prove cross-engine intensity parity or rendered illumination. A same-quality intensity-only diagnostic is appropriate after structural checks pass.']
    (out/'bsp010-light-audit.md').write_text('\n'.join(text)+'\n', encoding='utf-8')
    print(json.dumps(dict(output=str(out), status=result['status'], static_instances=len(result['instances']),
        scenario_rows=len(placements), emissive_mesh_groups=len(groups))))


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config', required=True)
    main(json.loads(Path(parser.parse_args().config).read_text(encoding='utf-8-sig')))

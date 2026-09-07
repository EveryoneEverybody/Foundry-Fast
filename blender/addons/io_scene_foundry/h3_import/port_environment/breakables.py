"""Placement inventory for BSP-owned breakable surfaces, not scenario objects.

Material identity joins are separate from the still-unresolved shard/support
relationship. Original rings and mapping tables stay in the semantic evidence.
"""
from collections import defaultdict
from copy import deepcopy

from .authoring import number


def shader_reference(material):
    reference = (material.get('render method') or {}) if material else {}
    path, extension = reference.get('path'), reference.get('extension')
    return (path.replace('\\', '/')+'.'+extension) if path and extension else None


def report(resolution):
    rows, contracts, definitions, surfaces, placed_surfaces = [], set(), set(), set(), set()
    for index, record in enumerate(resolution['records']):
        if not record['original_record']['source_field'].endswith('collision info.surfaces[].flags'):
            continue
        target = record['target_authoring_plan']
        evidence = target.get('source_evidence') or target.get('source') or {}
        affected = [s for s in evidence.get('collision_surfaces', []) if number(s['flags']) & 8]
        if not affected:
            continue
        rid = record['original_record_id']
        contracts.add(rid)
        bsp, definition = evidence['source_bsp'], evidence['source_definition']
        definitions.add((bsp, definition))
        surfaces.update((bsp, definition, s['source_surface']) for s in affected)
        materials = defaultdict(list)
        for surface in affected:
            materials[surface['material']].append(surface)
        groups = []
        for slot, selected in sorted(materials.items()):
            # -1 is unassigned, never Python's last material or an inferred sky.
            table = evidence['collision_materials']
            material = table[slot] if 0 <= slot < len(table) else None
            groups.append(dict(collision_material_index=slot, source_collision_material=material,
                collision_shader=shader_reference(material),
                material_status='SOURCE_SLOT_RESOLVED' if material is not None else 'UNASSIGNED' if slot == -1 else 'UNRESOLVED_SOURCE_INDEX',
                surface_count=len(selected), source_surface_indices=sorted(s['source_surface'] for s in selected),
                surface_flags=sorted({number(s['flags']) for s in selected}),
                breakable_surface_set_indices=sorted({s['breakable surface set'] for s in selected if 'breakable surface set' in s}),
                breakable_surface_indices=sorted({s['breakable surface'] for s in selected if 'breakable surface' in s})))
        expected = set(record['original_record']['affected_instances'])
        placements = evidence['placements']
        if len({p['source_index'] for p in placements}) != len(placements) or {p['source_index'] for p in placements} != expected:
            raise ValueError('Breakable placement accounting differs from original contract: '+rid)
        for placement in sorted(placements, key=lambda p:p['source_index']):
            if placement['instance definition'] != definition:
                raise ValueError('Breakable placement points to a different source definition: '+rid)
            pi = placement['source_index']
            placed_surfaces.update((bsp, definition, pi, s['source_surface']) for s in affected)
            rows.append(dict(original_record_id=rid, source_bsp=bsp, source_bsp_index=evidence['source_bsp_index'],
                source_bsp_sha256=record.get('provenance', {}).get('source_sha256'),
                source_zone=record.get('provenance'), source_definition=definition,
                definition_identity=evidence['definition_identity'], definition_storage='EMBEDDED_IN_BSP',
                definition_metadata=evidence['definition_metadata'], scenario_object_tag=None,
                placement_index=pi, source_object_name=placement.get('name'),
                object_name_evidence='Authored BSP instance placement name; no nearby-object inference',
                source_placement=placement, surface_count=len(affected), collision_materials=groups,
                source_render_mesh=evidence['source_mesh_index'], render_materials=evidence['render_materials'],
                render_material_relationship='Owning definition parts; material identity does not establish per-surface shard/support linkage',
                semantic='BSP_BREAKABLE_SURFACES', whole_instance_damage_state='NOT_ESTABLISHED',
                semantic_rule_id=record['semantic_rule_id'], resolution_class=record['resolution_class'],
                still_blocking=record['still_blocking'], missing_fact=target.get('missing_fact'),
                evidence=record['evidence'], full_topology=evidence['full_topology'],
                source_record_reference=f'source-semantic-resolution.json#/records/{index}/target_authoring_plan/'+
                    ('source_evidence' if 'source_evidence' in target else 'source')))
    rows.sort(key=lambda r:(r['source_bsp'], r['source_definition'], r['placement_index'], r['original_record_id']))
    return dict(format='foundry.h3-bsp-breakable-collision-report', version=1, native_writes=False,
        semantic='BSP_BREAKABLE_SURFACES', whole_instance_damage_state='NOT_ESTABLISHED',
        original_contract_count=len(contracts), definition_count=len(definitions),
        placement_count=len({(r['source_bsp'],r['placement_index']) for r in rows}),
        unique_definition_surface_count=len(surfaces), placed_surface_count=len(placed_surfaces),
        counting='Unique source surfaces counted once per BSP/definition; placed surfaces once per placement',
        evidence=['H3_ART', 'H3_BREAKABLE_HSC', 'H3_BREAKABLE_BSP_LINK', 'H3_COLLISION', 'REACH_FACES', 'SOURCE'],
        records=deepcopy(rows))


def markdown(result):
    lines = ['# H3 BSP breakable-surface inventory', '',
        f"{result['original_contract_count']} original contracts; {result['definition_count']} definitions; "
        f"{result['placement_count']} placements; {result['unique_definition_surface_count']} unique source surfaces; "
        f"{result['placed_surface_count']} placed surfaces.", '',
        'These are BSP breakable surfaces. Whole-instance damage-state behavior is not established. '
        'Names come directly from BSP placements; they do not imply scenario scenery tags.', '',
        '| Source BSP | Definition | Placement | Authored name | Collision material / shader | Render material / shader | Surfaces |',
        '|---|---:|---:|---|---|---|---:|']
    for r in result['records']:
        collision = '; '.join(f"{m['collision_material_index']}: {m['collision_shader']} ({m['surface_count']})" for m in r['collision_materials'])
        render = '; '.join(f"{m['source_material_slot']}: {m['source_shader']}" for m in r['render_materials'])
        values = [r['source_bsp'],r['source_definition'],r['placement_index'],r['source_object_name'],collision,render,r['surface_count']]
        lines.append('| '+' | '.join(str(v).replace('|','\\|').replace('\n',' ') for v in values)+' |')
    lines += ['', 'The JSON preserves source tag hashes, zone membership, placement transforms, collision flags, '
        'source surface IDs, breakable indices, material records and definition support metadata. '
        'Each row links to the original semantic record for rings, adjacent surfaces and render correspondence.', '',
        'A matching collision/render shader proves material identity, not the shard/support relationship. '
        'The conversion gate remains blocking until that relationship has a verified Reach authoring reconstruction.', '',
        'Evidence:', '',
        '- [C20 H3 materials](https://c20.reclaimers.net/h3/source-data/h3-materials/): `-` authors two-sided breakable geometry.',
        '- [C20 H3 scripting](https://c20.reclaimers.net/h3/engine/scripting/): `breakable_surfaces_enable` controls '
        'level breakability; `breakable_surfaces_reset` restores breakable surfaces.',
        '- The pinned TagTool BSP-to-object converter warns that removing BSP linkage requires removing the breakable flag. '
        'This supports the subsystem classification; it does not prove a Reach conversion.', '',
        'No Reach data/tags were written. No HSC was emitted or executed.', '']
    return '\n'.join(lines)

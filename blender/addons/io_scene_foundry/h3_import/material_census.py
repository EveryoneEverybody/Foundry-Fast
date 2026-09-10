"""Read-only translation inventory of a decoded scenario's material closure."""
from collections import Counter
from .material_translation import H3MaterialRecord, translate, canonical_json
from .material_writer import writer_issues


def census(manifest, environment_plan=None, *, destination_contracts=None):
    """Optional contracts are read-only native RMOP snapshots keyed by options JSON.

    ELIGIBLE means the plan fits those declarations, not that this material has
    been authored, rendered or that texture/geometry validation has occurred.
    """
    environment_plan = environment_plan or {}
    closure = sorted({r['source_shader'] for r in environment_plan.get('materials', ())}
                     if 'materials' in environment_plan else manifest['shaders'])
    usages = environment_plan.get('source_dependencies', {}).get('shader_usage', {})
    hashes = environment_plan.get('source', {}).get('hashes', {})
    records = []
    for path in closure:
        raw = manifest['shaders'].get(path, dict(source=path, group='', status='missing'))
        source = H3MaterialRecord.from_resolved(raw, manifest.get('bitmaps', {}),
                                               dict(source_sha256=hashes.get(path)))
        plan = translate(source)
        target = plan.to_dict()
        usage = usages.get(path, [])
        counts = Counter(u.get('kind', 'unknown') for u in usage)
        native = (destination_contracts or {}).get(canonical_json(target['options']))
        declarations = native.get('declarations') if native is not None else None
        boundary_issues = writer_issues(plan, declarations)
        if native is not None:
            boundary_issues.extend('UNRESOLVED_WRITER_RMOP: '+note for note in native.get('notes', ()))
        unresolved = [d for d in target['diagnostics'] if d.get('still_blocking', True)]
        losses = [d for d in target['diagnostics'] if not d.get('still_blocking', True)]
        records.append(dict(source_shader=path, source_identity=source.identity,
            source_group=source.source_group, source_material_model=source.material_model,
            source_definition=source.definition, source_categories=[dict(c) for c in source.categories],
            source_sha256=hashes.get(path), rule_id=plan.rule_id, rule_version=target['rule_version'],
            translation_status=plan.status, brdf_status=target['brdf_status'],
            target_model=target['options'].get('material_model'), target_options=target['options'],
            fields=target['field_origins'], destination_parameters=target['parameters'],
            compatibility_inputs=target['compatibility_inputs'],
            unresolved_reasons=unresolved, semantic_losses=losses, writer_issues=boundary_issues,
            writer_status='BLOCKED' if boundary_issues else ('ELIGIBLE' if declarations is not None else 'NOT_VALIDATED'),
            function_extern_status=target['function_extern_status'],
            usage=dict(entries=len(usage), kinds=dict(sorted(counts.items())),
                render_triangles=sum(u.get('placed_triangles', 0) for u in usage),
                collision_triangles=sum(u.get('triangles', 0) for u in usage),
                source_bsps=sorted({u['source_bsp'] for u in usage if u.get('source_bsp')}))))
    return dict(format='foundry.h3-reach-material-census', version=1,
        source_scenario=environment_plan.get('source', {}).get('scenario', manifest.get('source_tag')),
        source_plan_sha256=environment_plan.get('plan_sha256'), unique_materials=len(records),
        rule_counts=dict(sorted(Counter(r['rule_id'] or 'UNRESOLVED_REQUIRES_RULE' for r in records).items())),
        translation_status_counts=dict(sorted(Counter(r['translation_status'] for r in records).items())),
        brdf_status_counts=dict(sorted(Counter(r['brdf_status'] for r in records).items())),
        writer_status_counts=dict(sorted(Counter(r['writer_status'] for r in records).items())),
        writer_eligible_by_model=dict(sorted(Counter(r['source_material_model'] for r in records if r['writer_status']=='ELIGIBLE').items())),
        unresolved_reason_counts=dict(sorted(Counter(d['field']+': '+d['reason'] for r in records for d in r['unresolved_reasons']).items())),
        semantic_loss_counts=dict(sorted(Counter(d['field'] for r in records for d in r['semantic_losses']).items())),
        nonzero_semantic_loss_counts=dict(sorted(Counter(d['field'] for r in records for d in r['semantic_losses'] if d.get('source_value') != 0).items())),
        runtime_status='NOT_TESTED', records=records)


def markdown(report):
    lines = ['# H3 to Reach semantic material census', '',
             f"Unique materials: {report['unique_materials']}. Runtime: NOT_TESTED.", '',
             'Rule selection is separate from function/field resolution and writer acceptance.', '',
             'Writer ELIGIBLE means selected native RMOP declarations accept the plan; it is not runtime validation.', '',
             '| Rule | Selected |', '| --- | ---: |']
    lines += [f'| {rule} | {count} |' for rule, count in report['rule_counts'].items()]
    lines += ['', 'Writer counts: '+str(report['writer_status_counts']), '',
              'Losses (including zero values): '+str(report['semantic_loss_counts']), '',
              'Nonzero source values in those losses: '+str(report['nonzero_semantic_loss_counts']), '',
              '| Source | Model | Rule | Status | Uses | Writer | Losses |', '| --- | --- | --- | --- | ---: | --- | --- |']
    for row in report['records']:
        writer = '; '.join(row['writer_issues']).replace('|', '\\|')
        losses = '; '.join(f"{d['field']}={d.get('source_value')}: {d['reason']}" for d in row['semantic_losses'])
        lines.append(f"| {row['source_shader']} | {row['source_material_model']} | {row['rule_id'] or '-'} | {row['translation_status']} | {row['usage']['entries']} | {writer or row['writer_status']} | {losses} |")
    return '\n'.join(lines) + '\n'

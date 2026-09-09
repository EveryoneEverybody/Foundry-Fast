"""Read-only translation inventory of a decoded scenario's material closure."""
from collections import Counter
from .material_translation import H3MaterialRecord, translate
from .material_writer import writer_issues


def census(manifest, environment_plan=None):
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
        boundary_issues = writer_issues(plan)
        records.append(dict(source_shader=path, source_identity=source.identity,
            source_group=source.source_group, source_material_model=source.material_model,
            source_definition=source.definition, source_categories=[dict(c) for c in source.categories],
            source_sha256=hashes.get(path), rule_id=plan.rule_id, rule_version=target['rule_version'],
            translation_status=plan.status, brdf_status=target['brdf_status'],
            target_model=target['options'].get('material_model'), target_options=target['options'],
            fields=target['field_origins'], destination_parameters=target['parameters'],
            compatibility_inputs=target['compatibility_inputs'],
            unresolved_reasons=target['diagnostics'], writer_issues=boundary_issues,
            writer_status='BLOCKED' if boundary_issues else 'NOT_VALIDATED',
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
        runtime_status='NOT_TESTED', records=records)


def markdown(report):
    lines = ['# H3 to Reach semantic material census', '',
             f"Unique materials: {report['unique_materials']}. Runtime: NOT_TESTED.", '',
             'Rule selection is separate from function/field resolution and writer acceptance.', '',
             '| Rule | Selected |', '| --- | ---: |']
    lines += [f'| {rule} | {count} |' for rule, count in report['rule_counts'].items()]
    lines += ['', '| Source | Model | Rule | Status | Uses | Writer |', '| --- | --- | --- | --- | ---: | --- |']
    for row in report['records']:
        writer = '; '.join(row['writer_issues']).replace('|', '\\|')
        lines.append(f"| {row['source_shader']} | {row['source_material_model']} | {row['rule_id'] or '-'} | {row['translation_status']} | {row['usage']['entries']} | {writer or 'Requires native validation'} |")
    return '\n'.join(lines) + '\n'

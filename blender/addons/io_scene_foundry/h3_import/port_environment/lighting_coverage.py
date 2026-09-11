"""Known unresolved source contracts that must not become bake readiness."""


def source_coverage_gaps(bsp, scenario_fields=None, *, bsp_index=None):
    issues = []
    shared = [x.get('source_index', i) for i, x in enumerate(bsp.get('authoring', {}).get('instances', []))
              if x.get('lightmapping policy', {}).get('name') == 'per-pixel shared']
    if shared:
        issues.append(dict(bsp_index=bsp_index, feature='definition density', source_instances=shared,
            reason='H3 shared definition atlas sizing and definition/instance density composition '
                   'have no proven Reach transformation'))
    for name in ('flags', 'cloned bsp flags'):
        value = (scenario_fields or {}).get(name, '0')
        if int(value):
            issues.append(dict(bsp_index=bsp_index, feature='BSP lighting settings', field=name,
                source_value=value, reason='Nonzero H3 BSP source settings require an explicit '
                'semantic mapping; native zero defaults are not equivalence evidence'))
    return issues


def scenario_recipe_gaps(scenario_lights):
    """Do not infer dynamic-only behavior from a stored zero/default recipe."""
    issues = []
    for i, row in enumerate(scenario_lights.get('placements', [])):
        fields = [x['attributes'] for x in row['fields'] if x['element'] == 'field']
        types = [f.get('value') for f in fields if f.get('name') == 'type']
        if not types:
            issues.append(dict(feature='scenario light recipe', source_placement=i,
                               reason='Missing source scenario light palette binding'))
            continue
        raw = str(types[0]).rsplit(',', 1)[-1]
        try:
            bound = int(raw) != -1
        except ValueError:
            bound = True
        if bound:
            issues.append(dict(feature='scenario light recipe', source_placement=row.get('source_index', i),
                source_palette=raw, source_fields=fields,
                reason='Bound H3 scenario light bake relevance is unproven; '
                       'zero lightmap scale and use-light-tag defaults do not prove no contribution'))
    return issues

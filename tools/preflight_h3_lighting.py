"""Read-only, all-BSP lighting vocabulary and surface preparation preflight.

This reports translator coverage, not solver parity or native preparation success.
The output is user-selected evidence and must not be committed with the tooling.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                       'blender/addons/io_scene_foundry/h3_import'))
from port_environment.light_units import attenuation_record
from port_environment.surface_light_units import surface_preflight
from port_environment.lightmap_density import density_palette, source_density
from port_environment.lighting_coverage import source_coverage_gaps, scenario_recipe_gaps


def variants(records):
    """Retain every distinct source value, counts, owners and source identities."""
    grouped = {}
    for bsp, source, value in records:
        key = json.dumps(value, sort_keys=True)
        row = grouped.setdefault(key, dict(source_value=value, count=0, bsps=set(), sources=set()))
        row['count'] += 1
        row['bsps'].add(bsp)
        if source is not None:
            row['sources'].add(source)
    return [dict(row, bsps=sorted(row['bsps']), sources=sorted(row['sources']))
            for _, row in sorted(grouped.items())]


def census(plan):
    if len(plan['bsps']) != len(plan['lighting_by_bsp']):
        raise ValueError('Plan BSP/lighting count mismatch; refusing an incomplete census')
    surface, generic, fields, outcomes, densities, palettes = [], [], {}, [], [], []
    destinations = {m['source_shader']: m['destination'] for m in plan['materials']}
    for i, (bsp, lighting) in enumerate(zip(plan['bsps'], plan['lighting_by_bsp'])):
        source_rows = bsp['materials'][:len(bsp['authoring']['materials'])]
        errors = surface_preflight(source_rows, destinations, bsp_index=i)
        scenario_rows = plan.get('scenario', {}).get('source_semantics', {}).get('bsps', [])
        errors.extend(source_coverage_gaps(bsp, scenario_rows[i] if i < len(scenario_rows) else {}, bsp_index=i))
        for kind in ('instances', 'render_meshes'):
            for entry in bsp['authoring'].get(kind, []):
                for row in entry.get('parts', []) if kind == 'render_meshes' else [entry]:
                    for name in ('lightmapping policy', 'lightmap resolution scale', 'part type', 'part flags'):
                        if name in row:
                            fields.setdefault('receiver.' + name, []).append((i, None, row[name]))
        if i < len(scenario_rows):
            for name, value in scenario_rows[i].items():
                fields.setdefault('bsp.' + name, []).append((i, None, value))
        try:
            palette = density_palette(bsp['authoring']['materials'])
            palettes.append(dict(bsp_index=i, **palette, native_status='REQUIRES_PAIRED_NATIVE_VERIFICATION'))
            for slot, material in enumerate(bsp['authoring']['materials']):
                densities.append((i, source_rows[slot].get('source_shader'), source_density(material)))
        except (ValueError, KeyError, OverflowError) as exc:
            errors.append(dict(bsp_index=i, reason=str(exc), feature='material density'))
        for index, row in enumerate(lighting['source_semantics']['light_definitions']):
            if row['type'] not in {'omni', 'spot', 'directional'} or row['shape'] not in {'circle', 'rectangle'} or int(row['flags']) & ~3:
                errors.append(dict(bsp_index=i, definition_index=index, source_fields=row,
                                   reason='Unsupported source generic light type, shape or flags'))
        if len(lighting['definitions']) != len(lighting['source_semantics']['light_definitions']):
            errors.append(dict(bsp_index=i, reason='Source generic definitions were omitted from authoring'))
        for definition in lighting['definitions']:
            try:
                attenuation_record(definition)
            except (ValueError, KeyError, OverflowError) as exc:
                errors.append(dict(bsp_index=i, definition_index=definition.get('source_index'), reason=str(exc)))
        for row in lighting['source_semantics']['light_definitions']:
            generic.append((i, lighting['source_tag'], row))
            for name, value in row.items():
                fields.setdefault('generic.' + name, []).append((i, lighting['source_tag'], value))
        # Include unused/inactive source material rows separately from active emitters.
        for row in lighting['source_semantics']['materials']:
            for name, value in row.items():
                fields.setdefault('surface.all_rows.' + name, []).append((i, lighting['source_tag'], value))
        for material in source_rows:
            row = material.get('lighting', {})
            if float(row.get('emissive power', 0)) > 0:
                surface.append((i, material['source_shader'], row))
        outcomes.append(dict(bsp_index=i, status='STATIC_BLOCKED' if errors else 'STATIC_PASS', issues=errors))
    scenario_issues = scenario_recipe_gaps(plan.get('scenario_lights', {}))
    return dict(scope='All source BSP material rows, generic definitions and known unresolved lighting contracts; no native writes or solver execution',
                surface_variants=variants(surface), generic_variants=variants(generic),
                density_variants=variants(densities), density_palettes=palettes,
                field_variants={k: variants(v) for k, v in sorted(fields.items())}, bsps=outcomes,
                scenario_issues=scenario_issues,
                native_preparation='NOT_RUN')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = census(json.loads(args.plan.read_text(encoding='utf-8-sig')))
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return int(bool(report['scenario_issues']) or any(row['issues'] for row in report['bsps']))


if __name__ == '__main__':
    raise SystemExit(main())

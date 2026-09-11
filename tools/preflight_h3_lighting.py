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
    surface, generic, fields, outcomes = [], [], {}, []
    destinations = {m['source_shader']: m['destination'] for m in plan['materials']}
    for i, (bsp, lighting) in enumerate(zip(plan['bsps'], plan['lighting_by_bsp'])):
        source_rows = bsp['materials'][:len(bsp['authoring']['materials'])]
        errors = surface_preflight(source_rows, destinations, bsp_index=i)
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
    return dict(scope='All source BSP material rows and generic definitions; no native writes or solver execution',
                surface_variants=variants(surface), generic_variants=variants(generic),
                field_variants={k: variants(v) for k, v in sorted(fields.items())}, bsps=outcomes,
                native_preparation='NOT_RUN')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = census(json.loads(args.plan.read_text(encoding='utf-8-sig')))
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return int(any(row['issues'] for row in report['bsps']))


if __name__ == '__main__':
    raise SystemExit(main())

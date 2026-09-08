"""Isolated material-lightmap-power experiments, never converter defaults."""
from copy import deepcopy
import math

from . import fixtures, lighting_audit


def material_power_view(plan, source_bsp_index, source_slots, power, baseline_readback):
    if not math.isfinite(power) or not 0 < power <= 100:
        raise ValueError('Diagnostic material power must be finite, positive and at most 100')
    if not source_slots or len(set(source_slots)) != len(source_slots):
        raise ValueError('Select unique source material slots explicitly')
    matches = [i for i, b in enumerate(plan['bsps']) if b['source_index'] == source_bsp_index]
    if len(matches) != 1:
        raise ValueError('Diagnostic requires one accepted source BSP')
    index = matches[0]
    bsp = plan['bsps'][index]
    readbacks = [b for b in baseline_readback['bsps'] if b['bsp'] == bsp['destination']]
    if baseline_readback['status'] != 'VERIFIED_BEFORE_FAUX' or len(readbacks) != 1:
        raise ValueError('Missing verified native material identity readback')
    bindings = {r['source_material']: r for r in readbacks[0]['emissive']}
    native_rows = set()
    selected = []
    for slot in source_slots:
        if slot not in bindings or not 0 <= slot < len(bsp['materials']):
            raise ValueError('Diagnostic material lacks verified native identity')
        row, binding = bsp['materials'][slot], bindings[slot]
        source_power = float(row.get('lighting', {}).get('emissive power', 0))
        if source_power <= 0 or power <= source_power or row['source_shader'] != binding['source_shader']:
            raise ValueError('Diagnostic requires an existing positive material and elevated power')
        if not binding['native_material_info_indices']:
            raise ValueError('No native material rows')
        native_rows.update(binding['native_material_info_indices'])
        selected.append(dict(source_slot=slot, source_shader=row['source_shader'],
            source_lighting_index=row['source_lighting_index'], baseline_power=source_power,
            diagnostic_power=power, native_rows=sorted(set(binding['native_material_info_indices']))))
    # A deduplicated native row can serve several source slots. Reject a partial
    # selection instead of silently changing another source material variant.
    for slot, binding in bindings.items():
        if slot not in source_slots and native_rows.intersection(binding['native_material_info_indices']):
            raise ValueError('Selected native row also belongs to an unselected source material')
    view = deepcopy(plan)
    for slot in source_slots:
        view['bsps'][index]['materials'][slot]['lighting']['emissive power'] = str(power)
    return view, index, sorted(native_rows), selected


def assert_material_power_delta(baseline, actual, rows, power):
    """Only selected material-info powers may differ in complete Tool XML."""
    before = fixtures.parse(baseline)
    after = fixtures.parse(actual)
    expected_rows = fixtures.block(before, 'material info')
    actual_rows = fixtures.block(after, 'material info')
    if len(expected_rows) != len(actual_rows) or not rows or len(set(rows)) != len(rows):
        raise ValueError('Material row selection/count changed')
    for index in rows:
        if not 0 <= index < len(expected_rows):
            raise ValueError('Material row outside native table')
        fields = [e for e in expected_rows[index] if e.get('name') == 'emissive power']
        native = [e for e in actual_rows[index] if e.get('name') == 'emissive power']
        if len(fields) != 1 or len(native) != 1 or float(fields[0].get('value')) <= 0:
            raise ValueError('Missing/invalid emissive material power')
        if not lighting_audit.equivalent(float(native[0].get('value')), power):
            raise ValueError('Diagnostic material power readback mismatch')
        # Normalize only the explicitly allowed value, then compare every XML
        # field, ordered row, reference and block marker, not just key samples.
        native[0].set('value', fields[0].get('value'))
    def canonical(root):
        return [(e.tag, sorted(e.attrib.items()), (e.text or '').strip(), (e.tail or '').strip()) for e in root.iter()]
    if canonical(before) != canonical(after):
        raise ValueError('Diagnostic changed a field other than selected material powers')
    return dict(status='MATERIAL_POWER_ONLY', native_material_info_rows=rows, power=power,
                generic_lights_unchanged=True, other_material_fields_unchanged=True)

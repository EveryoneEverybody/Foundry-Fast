"""Translate H3 surface-emitter distance semantics at the Reach boundary."""
import math
from copy import deepcopy
from .light_units import REACH_ATTENUATION_AUTHORING_SCALE

# H3 surface emitters substitute these finite world distances when the source
# attenuation flag is clear. Reach's zero-distance defaults are different.
H3_DISABLED_SURFACE_RANGE = (20.0, 21.0)
RANGE_FIELDS = ('attenuation falloff', 'attenuation cutoff')


def surface_attenuation_record(source):
    flags = int(source['flags'])
    if flags & ~3 or float(source.get('frustum blend', 0)):
        raise ValueError('Unsupported H3 surface emission flags or frustum blend')
    stored = [float(source[k]) for k in RANGE_FIELDS]
    enabled = bool(flags & 1)
    effective = stored if enabled else H3_DISABLED_SURFACE_RANGE
    if any(not math.isfinite(x) or x < 0 or x * REACH_ATTENUATION_AUTHORING_SCALE > 3.402823466e38 for x in effective):
        raise ValueError('Surface attenuation must fit nonnegative float32 authoring distances')
    # Zero/zero invokes different target defaults. Do not silently translate it.
    if enabled and effective[1] <= effective[0]:
        raise ValueError('Explicit H3 surface attenuation requires cutoff above falloff')
    return {
        'SOURCE_H3_SEMANTICS': dict(attenuation_enabled=enabled, stored_distances=dict(zip(RANGE_FIELDS, stored))),
        'REACH_AUTHORING_VALUES': dict(zip(RANGE_FIELDS, (x * REACH_ATTENUATION_AUTHORING_SCALE for x in effective))),
        'EXPECTED_FAUX_EFFECTIVE_VALUES': dict(zip(RANGE_FIELDS, (effective[0], max(effective[1], effective[0] + 0.001)))),
    }


def surface_native_updates(materials, destinations, bsp_materials, native_rows):
    """Resolve source provenance to existing native rows; reject stale/ambiguous data."""
    updates = {}
    def same(a, b):
        if isinstance(a, (tuple, list)): return len(a) == len(b) and all(same(x,y) for x,y in zip(a,b))
        return math.isclose(float(a), float(b), rel_tol=2e-6, abs_tol=2e-5)
    for material in materials:
        source = material.get('lighting', {})
        if float(source.get('emissive power', 0)) <= 0: continue
        record = surface_attenuation_record(source)
        shader = destinations[material['source_shader']].replace('\\', '/')
        expected = {k: float(source[k]) for k in ('emissive power','emissive focus','emissive quality')}
        expected['emissive color'] = [float(x) for x in source['emissive color'].split(',')]
        if material.get('emissive_authoring'):
            expected['emissive focus'] = 1-material['emissive_authoring']['target']['foundry_emissive_spread_radians']/math.pi
        matches=[]
        for m in bsp_materials:
            if m['render method'] != shader: continue
            index=int(m['imported material index'])
            if not 0 <= index < len(native_rows): raise ValueError('Native surface material index outside table')
            row=native_rows[index]
            if not all(same(row[k],v) for k,v in expected.items()): continue
            if int(row['flags']) != (int(source['flags']) & 2) or not same(row['bounce ratio'],1):
                raise ValueError('Unexpected surface flags/bounce; refusing overwrite')
            old={k:float(source[k]) for k in RANGE_FIELDS}
            if not any(all(same(row[k],v[k]) for k in RANGE_FIELDS) for v in (old,record['REACH_AUTHORING_VALUES'])):
                continue
            matches.append(index)
        if not matches: raise ValueError('No matching native surface row for '+material['source_shader'])
        for index in set(matches):
            if index in updates and updates[index]['REACH_AUTHORING_VALUES'] != record['REACH_AUTHORING_VALUES']:
                raise ValueError('Conflicting source semantics share native surface row')
            updates[index]=dict(deepcopy(record), native_row=index, source_slot=material['slot'], source_shader=material['source_shader'],
                               old_values={k:native_rows[index][k] for k in RANGE_FIELDS})
    return list(updates.values())


def write_surface_attenuation(tag, records):
    """Write only the two ranges in resolved existing native material rows."""
    rows=tag.SelectField('material info').Elements
    for record in records:
        element=rows[record['native_row']]
        for key,value in record['REACH_AUTHORING_VALUES'].items(): element.SelectField(key).Data=value

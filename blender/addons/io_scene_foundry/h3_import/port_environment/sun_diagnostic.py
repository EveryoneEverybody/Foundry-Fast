"""Sun-input positive control; no permanent source or sky appearance changes."""
from copy import deepcopy
import math

from . import fixtures, lighting_audit


def sun_view(plan, sky_index, factor):
    if not math.isfinite(factor) or not 0 < factor < 1:
        raise ValueError('Sun control requires a finite factor between zero and one')
    if not 0 <= sky_index < len(plan['skies']):
        raise ValueError('Sun control must select an existing sky')
    sky = plan['skies'][sky_index]
    source = sky['lighting']['sun_irradiance']
    if len(source) != 3 or not all(math.isfinite(x) and x >= 0 for x in source) or not max(source):
        raise ValueError('Sun control requires positive accepted irradiance')
    view = deepcopy(plan)
    values = [x * factor for x in source]
    view['skies'][sky_index]['lighting']['sun_irradiance'] = values
    # Diffuse sky samples, including their source provenance, stay unchanged.
    return view, sky['destination'].rsplit('.', 1)[0] + '.render_model', values


def assert_sun_delta(baseline, actual, factor):
    """Compare complete Tool XML, permitting only the analytic sun RGB scale."""
    if not math.isfinite(factor) or not 0 < factor < 1:
        raise ValueError('Invalid sun control factor')
    before, after = fixtures.parse(baseline), fixtures.parse(actual)
    def values(root):
        arrays = [e for e in root if e.tag == 'array' and e.get('name') == 'sun']
        if len(arrays) != 1:
            raise ValueError('Missing analytic sun array')
        fields = [f for e in arrays[0] for f in e if f.tag == 'field']
        if len(fields) != 6:
            raise ValueError('Expected analytic sun direction and RGB')
        return fields
    a, b = values(before), values(after)
    if not any(float(f.get('value')) > 0 for f in a[3:]):
        raise ValueError('Baseline sun has no power')
    for x, y in zip(a[3:], b[3:]):
        if not lighting_audit.equivalent(float(y.get('value')), float(x.get('value')) * factor):
            raise ValueError('Sun control readback mismatch')
        y.set('value', x.get('value'))
    def canonical(root):
        return [(e.tag, sorted(e.attrib.items()), (e.text or '').strip(), (e.tail or '').strip()) for e in root.iter()]
    if canonical(before) != canonical(after):
        raise ValueError('Sun control changed another sky field')
    return dict(status='SUN_IRRADIANCE_ONLY', factor=factor,
                geometry_and_materials_unchanged=True, diffuse_samples_unchanged=True)

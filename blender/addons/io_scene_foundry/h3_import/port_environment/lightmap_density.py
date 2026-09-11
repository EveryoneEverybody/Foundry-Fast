"""Lossless material density palettes at the Reach authoring boundary.

H3 material property zero stores a float (absent means one). Reach stores
a one-based index into seven scenario BSP floats, not the source multiplier.
Definition atlas sizing is a separate contract and is not converted here.
"""
import math
import struct

BUCKET_FIELDS = ('lightmap res lowest', 'lightmap res 2nd low',
                 'lightmap res 3rd low', 'lightmap res medium',
                 'lightmap res 3rd high', 'lightmap res 2nd high',
                 'lightmap res highest')


def ignore_target_default(source_shader):
    # These H3 receiver classes all use a unit class factor. Reach foliage
    # otherwise introduces a 0.001 factor. Its explicit override restores one.
    if source_shader.rsplit('.', 1)[-1] not in {'shader', 'shader_terrain', 'shader_foliage'}:
        raise ValueError('Unproven H3 receiver class density factor')
    return True


def source_density(material):
    rows = [p for p in material.get('properties', [])
            if p['type']['name'] == 'lightmap resolution']
    if len(rows) > 1:
        raise ValueError('Duplicate H3 material lightmap resolution properties')
    value = rows[0]['real-value'] if rows else 1.0
    if isinstance(value, dict):
        value = value['values'][0]
    value = float(value)
    if not math.isfinite(value) or value < 0.0001 or value > 3.402823466e38:
        raise ValueError('H3 material density cannot be represented without Reach clamping')
    return struct.unpack('<f', struct.pack('<f', value))[0]


def density_palette(materials):
    """Deterministic exact slots, including the absent-property default."""
    densities = [source_density(m) for m in materials]
    values = [1.0, *sorted(set(densities) - {1.0})]
    if len(values) > len(BUCKET_FIELDS):
        raise ValueError('More than seven H3 material densities require another exact representation')
    return dict(bucket_values=values + [1.0] * (len(BUCKET_FIELDS) - len(values)),
                material_indices=[values.index(v) + 1 for v in densities],
                source_densities=densities)


def write_density_palette(bsp_element, palette):
    block = bsp_element.SelectField('lightmap setting')
    if block.Elements.Count > 1:
        raise ValueError('Ambiguous native BSP lightmap settings')
    element = block.Elements[0] if block.Elements.Count else block.AddElement()
    for name, value in zip(BUCKET_FIELDS, palette['bucket_values'], strict=True):
        element.SelectField(name).Data = value


def native_density_issues(materials, source_rows, destinations, native_materials,
                          bsp_settings, *, bsp_index=None):
    """Report definite mismatches without guessing merged native material ownership.

Missing source rows and ambiguous ownership are not evidence of equivalence.
This checks whether any candidate can carry each source density; it does not
authorize rewriting material indices based on shader identity alone.
"""
    issues = []
    if len(bsp_settings) != 1:
        return [dict(bsp_index=bsp_index, reason='Missing or ambiguous native density palette')]
    buckets = [float(bsp_settings[0][k]) for k in BUCKET_FIELDS]
    for slot, (material, row) in enumerate(zip(materials, source_rows, strict=True)):
        expected = source_density(material)
        shader = row.get('source_shader')
        destination = destinations.get(shader)
        if not shader or not destination:
            continue
        ignore_target_default(shader)
        candidates = []
        for i, native in enumerate(native_materials):
            if native['render method'].replace('\\', '/') != destination:
                continue
            index = int(native['lightmap resolution scale'])
            effective = max(0.0001, buckets[index - 1]) if 1 <= index <= 7 else 1.0
            if destination.endswith('.shader_foliage') and not int(native['lightmap flags']) & 1:
                effective *= 0.001
            candidates.append(dict(material_index=i, index=index, density=effective))
        if candidates and not any(c['density'] == expected for c in candidates):
            issues.append(dict(bsp_index=bsp_index, source_material_slot=slot,
                source_shader=shader, destination_material=destination,
                source_density=expected, native_candidates=candidates,
                reason='Native material density differs from H3; regenerate source face indices '
                       'with their paired BSP density palette before baking'))
    return issues

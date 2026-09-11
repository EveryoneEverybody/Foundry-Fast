"""Native adapter for incremental population; never rebuild scenario tables."""
import math
from copy import deepcopy

from . import native_placements as placements, native_object_tags, native_zones, population, scenario_ir
from .model import stable_hash


def group_semantic(records):
    return dict(initial_value=float(placements.first(records, 'initial value')['value']),
                flags=sorted(native_object_tags.normalized(n) for n in
                             placements.first(records, 'flags').get('set_flags', [])))


def flags(field):
    return sorted(native_object_tags.normalized(i.FlagName) for i in field.Items if field.TestBit(i.FlagName))


def native_identity(element, palette):
    pi = int(element.SelectField('type').Value)
    d = element.SelectField('object data').Elements[0]
    return dict(target_palette_index=pi,
                target_tag=palette[pi]['target_tag'] if 0 <= pi < len(palette) else '',
                target_object_name_index=int(element.SelectField('name').Value),
                unique_id=str(d.SelectField('object id').Elements[0].SelectField('unique id').Data))


def snapshot(tag, fingerprints):
    """Fingerprints are full per-element Tool XML hashes, including foreign fields."""
    s = tag.tag.SelectField
    names = [dict(name=e.SelectField('name').GetStringData(), uses=[])
             for e in s('object names').Elements]
    groups = [dict(name=e.SelectField('name').GetStringData(), semantic=dict(
        initial_value=float(e.SelectField('initial value').Data), flags=flags(e.SelectField('flags'))))
        for e in s('device groups').Elements]
    families = {}
    # Include unselected families when establishing name ownership.
    for family, (palette_name, _, _, _) in scenario_ir.FAMILIES.items():
        block = s(family)
        if block is None:
            continue
        if family in placements.SUPPORTED:
            palette = [dict(target_tag=population.canonical(str(e.SelectField('name').Path.RelativePathWithExtension))
                            if e.SelectField('name').Path else '') for e in s(palette_name).Elements]
            rows = []
            for i, e in enumerate(block.Elements):
                row = native_identity(e, palette)
                row.update(fingerprint=fingerprints[family][i], native_index=i, family=family)
                rows.append(row)
            families[family] = dict(palette=palette, placements=rows)
        for i, e in enumerate(block.Elements):
            ni = int(e.SelectField('name').Value)
            if ni >= 0:
                if ni >= len(names):
                    raise ValueError('Target placement name index is out of bounds')
                names[ni]['uses'].append(dict(family=family, index=i))
    return dict(object_names=names, device_groups=groups, families=families)


def verify_element(element, row):
    """Verify every source-authored field written by object_element after reopen."""
    s = element.SelectField
    if int(s('type').Value) != row['target_palette_index'] or int(s('name').Value) != row['target_object_name_index']:
        raise ValueError('Native palette/name remapping differs')
    records = placements.placement_records(row)
    data = s('object data').Elements[0]
    placements.verify_xml(records, data, ('placement flags', 'bsp policy', 'manual bsp flags',
                                          'transform flags', 'light airprobe name', 'can attach to bsp flags'))
    for name, expected in [('position', row['position_world']), ('rotation', row['rotation_degrees']), ('scale', [row['scale']])]:
        value = data.SelectField(name).Data
        actual = [float(value)] if name == 'scale' else list(value)
        if len(actual) != len(expected) or any(not math.isclose(a, b, abs_tol=2e-4, rel_tol=1e-6) for a, b in zip(actual, expected)):
            raise ValueError('Native transform differs: ' + name)
    placements.verify_xml(placements.section(records, 'object id'), data.SelectField('object id').Elements[0],
                         ('unique id', 'origin bsp index', 'type', 'source'))
    placements.verify_xml(placements.section(records, 'parent id'), data.SelectField('parent id').Elements[0],
                         ('parent object', 'parent marker', 'connection marker'))
    permutation = s('permutation data').Elements[0]
    placements.verify_xml(records, permutation, ('variant name', 'active change colors'))
    if row['family'] in {'machines', 'controls'}:
        placements.verify_xml(placements.section(records, 'device data'), s('device data').Elements[0],
                             ('power group', 'position group', 'flags'))
        block = 'machine data' if row['family'] == 'machines' else 'control data'
        placements.verify_xml(placements.section(records, block), s(block).Elements[0],
                             ('flags', 'pathfinding policy', 'health station charges'))
    elif row['family'] == 'scenery':
        placements.verify_xml(placements.section(records, 'scenery data'), s('scenery data').Elements[0],
                             ('Pathfinding policy', 'Lightmapping policy'))
    return True


def plan(tag, translation, fingerprints, *, families=placements.SUPPORTED, provenance=None):
    source = deepcopy(translation)
    for row in source['device_groups']:
        row['semantic'] = group_semantic(row['source_records'])
    try:
        contract = placements.structure_origin_contract(tag, source)
    except ValueError as exc:
        contract = dict(status='DEFERRED', reason=str(exc))
        for f in families:
            for row in source['families'][f]['placements']:
                if placements.first(placements.section(row['source_records'], 'object id'), 'source')['value'] == 'structure':
                    row.update(native_status='DEFERRED', reason=str(exc))
    state = snapshot(tag, fingerprints)
    def equivalent(existing, desired):
        try:
            return verify_element(tag.tag.SelectField(existing['family']).Elements[existing['native_index']], desired)
        except ValueError:
            return False
    result = population.reconcile(source, state, families=families, provenance=provenance, equivalent=equivalent)
    result['structure_origin_contract'] = contract
    result['designer_zone_additions'] = []
    zones = tag.tag.SelectField('designer zones').Elements
    for zone in source['structure']['designer_zones']:
        found = [i for i, e in enumerate(zones) if e.SelectField('name').GetStringData() == zone['name']]
        if len(found) != 1:
            # Zone creation/replacement is intentionally outside this adapter.
            raise ValueError('Missing or ambiguous existing designer zone: ' + zone['name'])
        zi = found[0]
        for record in zone['source_records']:
            f = next((f for f in families if placements.KINDS[f] == record['name']), None)
            if record['kind'] != 'block' or f is None:
                continue
            block = zones[zi].SelectField('Block:' + record['name'])
            existing = {int(e.SelectField('palette index').Value) for e in block.Elements}
            for member in record['elements']:
                si = int(placements.first(member, 'palette index')['value'].rsplit(',', 1)[-1])
                pi = result['palette_maps'][f].get(si)
                if pi is not None and pi not in existing:
                    addition = dict(zone_index=zi, family=f, target_palette_index=pi)
                    result['designer_zone_additions'].append(addition)
                    result['mutations'].append(dict(table='designer_zone_membership', **addition))
                    existing.add(pi)
    result['semantic_mutation_count'] = len(result['mutations'])
    result['plan_sha256'] = stable_hash({k: v for k, v in result.items() if k != 'plan_sha256'})
    return result


def apply(tag, result, translation):
    """Append only planned entries and update only proven owned placements.

    Save once, explicitly, after every write succeeds. Disable context-manager
    autosave even on exceptions, since that manager saves on exceptional exit.
    """
    if result['mode'] != population.MODE:
        raise ValueError('Explicit population mode required')
    if not result['semantic_mutation_count']:
        return dict(saved=False, semantic_mutations=0)
    s = tag.tag.SelectField
    tag.tag_has_changes = False
    tag.always_save = False
    for mutation in result['mutations']:
        table = mutation['table']
        if table not in {'palette', 'object_names', 'device_groups'}:
            continue
        name = scenario_ir.FAMILIES[mutation['family']][0] if table == 'palette' else table.replace('_', ' ')
        block = s(name)
        if block.Elements.Count != mutation['index']:
            raise ValueError('Target table changed since population planning: ' + name)
        e = block.AddElement()
        if table == 'palette':
            e.SelectField('name').Path = tag._TagPath_from_string(mutation['target_tag'])
        elif table == 'object_names':
            e.SelectField('name').SetStringData(mutation['name'])
            e.SelectField('object_type').Value = -1
            e.SelectField('scenario_datum_index').Value = -1
        else:
            row = next(r for r in translation['device_groups'] if r['source_index'] == mutation['source_index'])
            placements.copy(row['source_records'], e, ('name', 'initial value', 'flags'))
            e.SelectField('editor folder').Value = -1
    for row in result['placements']:
        if row['action'] == 'UNCHANGED':
            continue
        block = s(row['family'])
        if row['action'] == 'APPEND':
            if block.Elements.Count != row['target_index']:
                raise ValueError('Target placement count changed since planning')
            e = block.AddElement()
        else:
            e = block.Elements[row['target_index']]
        placements.object_element(e, row, preserve_target_metadata=row['action']=='UPDATE')
        verify_element(e, row)
    for row in result['designer_zone_additions']:
        block = s('designer zones').Elements[row['zone_index']].SelectField('Block:' + placements.KINDS[row['family']])
        block.AddElement().SelectField('palette index').Value = row['target_palette_index']
    tag.tag.Save()
    return dict(saved=True, semantic_mutations=result['semantic_mutation_count'])

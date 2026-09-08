"""Source identities and authoring relationships for a complete H3 scenario.

Compiled PVS, AI, scripts and runtime resources are evidence only. A planned
translation never counts as a generated native object. H3 Tool's flattened
struct markers and repeated field names are retained in ordered records.
"""
from collections import Counter
from copy import deepcopy
import re

from . import fixtures
from .model import finite, stable_hash
from .paths import relative
from .selection import optional_block, select, index


FAMILIES = {
    'scenery': ('scenery palette', 'scenery', 'NATIVE_REBUILD', 'Shared model/render/collision authoring'),
    'crates': ('crate palette', 'crate', 'NATIVE_REBUILD', 'Shared object authoring plus native rigid-body physics'),
    'machines': ('machine palette', 'device_machine', 'NATIVE_REBUILD', 'Shared object authoring plus bounded device animation/state'),
    'controls': ('control palette', 'device_control', 'NATIVE_REBUILD', 'Shared object authoring plus control state and device groups'),
    'sound scenery': ('sound scenery palette', 'sound_scenery', 'RUNTIME_LATER', 'Native audio dependency conversion is not implemented'),
    'effect scenery': ('effect scenery palette', 'effect_scenery', 'RUNTIME_LATER', 'Native effect dependency conversion is not implemented'),
    'light volumes': ('light volumes palette', 'light', 'RUNTIME_LATER', 'Scenario light volume functions require a separate native mapping'),
    'terminals': ('terminal palette', 'device_terminal', 'RUNTIME_LATER', 'Terminal interaction and content need a separate mapping'),
    'bipeds': ('biped palette', 'biped', 'RUNTIME_LATER', 'Unit and character animation systems are explicitly deferred'),
    'vehicles': ('vehicle palette', 'vehicle', 'RUNTIME_LATER', 'Vehicle, seat and vehicle physics systems are explicitly deferred'),
    'giants': ('giant palette', 'giant', 'RUNTIME_LATER', 'Unit, giant and AI systems are explicitly deferred'),
    'creatures': ('creature palette', 'creature', 'RUNTIME_LATER', 'Creature and unit simulation are explicitly deferred'),
    'weapons': ('weapon palette', 'weapon', 'RUNTIME_LATER', 'Weapon gameplay and unit dependencies are outside this milestone'),
    'equipment': ('equipment palette', 'equipment', 'RUNTIME_LATER', 'Equipment gameplay is outside this milestone'),
}
FIELDS = frozenset({
    'type', 'flags', 'structure bsps', 'structure seams', 'skies', 'zone sets',
    'lighting zone sets', 'object names', 'device groups', 'reference frames', 'designer zones',
    'player starting locations', 'player starting profile', 'cutscene flags',
    'zone set switch trigger volumes', 'trigger volumes', 'soft ceilings',
    *FAMILIES, *(v[0] for v in FAMILIES.values()),
})


def records(node):
    """Retain order/duplicate names without embedding opaque source payloads."""
    rows = []
    for element in node:
        row = dict(kind=element.tag, name=element.get('name'), type=element.get('type'))
        if element.tag == 'field':
            if element.get('type') in {'data', 'pageable resource', 'pad', 'skip'}:
                row['disposition'] = 'SOURCE_OPAQUE_DATA_NOT_COPIED'
            else:
                row['value'] = element.get('value')
                if 'flags' in element.get('type', ''):
                    row['set_flags'] = [v.strip() for v in (element.text or '').splitlines() if v.strip()]
        elif element.tag == 'block':
            elements = fixtures.block(node, element.get('name'))
            row.update(count=len(elements), elements=[records(e) for e in elements])
        rows.append(row)
    return rows


def first(node, name, default=None):
    return next((e.get('value') for e in node if e.tag == 'field' and e.get('name') == name), default)


def vector(node, name):
    return finite([float(v) for v in first(node, name).split(',')], 3)


def remap_mask(mask, mapping, source_count):
    if type(mask) is not int or mask < 0 or mask >> source_count:
        raise ValueError('Source BSP mask references an absent BSP')
    absent = [i for i in range(source_count) if mask & (1 << i) and i not in mapping]
    if absent:
        raise ValueError('Cannot silently drop BSP membership: '+str(absent))
    return sum(1 << mapping[i] for i in range(source_count) if mask & (1 << i))


def select_all(root, source_scenario, initial_zone=None, spawn_flag=None):
    """Select all source geometry but retain the actual zone table separately.

    The temporary union is solely a decode selection. It is never a target
    zone set, including when an authored zone happens to be named 'all'.
    """
    bsps = fixtures.block(root, 'structure bsps')
    zones = fixtures.block(root, 'zone sets')
    if not zones or not 0 < len(bsps) <= 32:
        raise ValueError('A complete scenario requires authored zones and 1..32 BSPs')
    names = [fixtures.field(z, 'name') for z in zones]
    if any(not n for n in names) or len(set(names)) != len(names):
        raise ValueError('Authored zone-set names must be nonempty and unique')
    initial_zone = initial_zone or names[0]
    if initial_zone not in names:
        raise ValueError('Initial zone is not authored: '+initial_zone)
    selected_root = deepcopy(root)
    zone_block = next(e for e in selected_root if e.get('name') == 'zone sets')
    for child in zone_block:
        if first(child, 'name') == initial_zone:
            for field in child:
                if field.get('name') == 'bsp zone flags':
                    field.set('value', str((1 << len(bsps))-1))
    result = select(selected_root, source_scenario, initial_zone, spawn_flag)
    mapping = {b['source_index']: b['target_index'] for b in result['bsps']}
    design_indices = {b['source_index']: i for i, b in enumerate(b for b in result['bsps'] if b['structure_design'])}
    translated = []
    for i, row in enumerate(zones):
        source_mask = int(fixtures.field(row, 'bsp zone flags'))
        target_mask = remap_mask(source_mask, mapping, len(bsps))
        previous = index(first(row, 'hint previous zone set', ',-1'))
        if not -1 <= previous < len(zones):
            raise ValueError('Invalid previous zone-set relationship')
        translated.append(dict(source_index=i, target_index=i, source_name=names[i], target_name=names[i],
            source_bsp_mask=source_mask, target_bsp_mask=target_mask,
            target_design_mask=sum(1 << di for bi, di in design_indices.items() if source_mask & (1 << bi)),
            source_fields=fixtures.fields(row), hint_previous_zone_set=previous,
            classification='NATIVE_TRANSFORM', native_status='NOT_GENERATED',
            pvs_policy='REBUILD_WITH_REACH_TOOL', audibility_policy='REBUILD_WITH_REACH_TOOL'))
    initial = translated[names.index(initial_zone)]
    result.update(scope='FULL_SCENARIO', zone_sets=translated,
        designer_zones=[dict(source_index=i, target_index=i, name=first(e, 'name'),
                            source_records=records(e)) for i,e in enumerate(optional_block(root,'designer zones'))],
        geometry_source_bsp_mask=(1 << len(bsps))-1,
        source_bsp_mask=initial['source_bsp_mask'], target_bsp_mask=initial['target_bsp_mask'],
        source_zone_index=initial['source_index'], source_zone_fields=initial['source_fields'])
    # Source sky activation is independent of a BSP's default-sky selection.
    for sky in result['skies']:
        sky['active_bsp_mask'] = remap_mask(sky['source_active_bsp_mask'], mapping, len(bsps))
    return result


def top_level_counts(path):
    """Stream only block headers; do not walk compiled campaign payloads."""
    counts = {}
    with open(path, 'rb') as stream:
        for line in stream:
            match = re.match(rb'    <block name="([^"]*)" value="[^"]*,(\d+)">', line)
            if match:
                name = match[1].decode('utf-8')
                if name in counts:
                    raise ValueError('Repeated source section: '+name)
                counts[name] = int(match[2])
    return counts


def placement(node, family, palette, names, bsp_count, group_count):
    pi, ni = index(first(node, 'type')), index(first(node, 'name'))
    problems = []
    if not 0 <= pi < len(palette):
        problems.append('Source palette index is absent')
    if not -1 <= ni < len(names):
        problems.append('Source object name index is absent')
    position, rotation = vector(node, 'position'), vector(node, 'rotation')
    scale = float(first(node, 'scale', '0'))
    finite([scale], 1)
    if scale < 0:
        problems.append('Negative scale requires an explicit winding/physics rule')
    parent = index(first(node, 'parent object', ',-1'))
    if not -1 <= parent < len(names):
        problems.append('Source parent object name index is absent')
    groups = {key: index(first(node, key, ',-1')) for key in ('power group', 'position group')}
    if any(not -1 <= value < group_count for value in groups.values()):
        problems.append('Source device group index is absent')
    manual = int(first(node, 'manual bsp flags', '0'))
    if manual < 0 or manual >> bsp_count:
        problems.append('Manual BSP mask references an absent source BSP')
    orientations = optional_block(node, 'node orientations')
    name = names[ni]['name'] if 0 <= ni < len(names) else None
    return dict(family=family, source_index=int(node.get('index')), source_palette_index=pi,
        target_palette_index=None, source_tag=palette[pi]['source_tag'] if 0 <= pi < len(palette) else None,
        source_object_name_index=ni, source_object_name=name, target_object_name=name,
        target_index=None, position_world=position, rotation_degrees=rotation,
        source_scale=scale, scale=1.0 if scale == 0 else scale,
        scale_rule='H3_ZERO_MEANS_DEFAULT_ONE' if scale == 0 else 'SOURCE_VALUE',
        variant=first(node, 'variant name', ''), placement_flags=int(first(node, 'placement flags', '0')),
        parent=dict(source_name_index=parent, parent_marker=first(node, 'parent marker', ''),
                    connection_marker=first(node, 'connection marker', '')),
        device_groups=groups, source_manual_bsp_mask=manual,
        source_origin_bsp=index(first(node, 'origin bsp index', ',-1')),
        bsp_policy=first(node, 'bsp policy'), unique_id=first(node, 'unique id'),
        stored_pose_count=len(orientations), stored_pose_status='DEFERRED' if orientations else 'ABSENT',
        source_records=records(node), classification='BLOCKING_UNKNOWN' if problems else FAMILIES[family][2],
        reason='; '.join(problems) if problems else FAMILIES[family][3],
        native_status='NOT_GENERATED', runtime_status='NOT_TESTED', source_problems=problems)


def inventory(root, selection, counts, *, source_sha256, xml_sha256):
    names = [dict(source_index=i, name=first(e, 'name'), source_object_type=index(first(e, 'object_type')),
                  source_placement_index=index(first(e, 'scenario_datum_index')))
             for i, e in enumerate(optional_block(root, 'object names'))]
    groups = [dict(source_index=i, target_index=i, name=first(e, 'name'),
                   initial_value=float(first(e, 'initial value')), source_records=records(e),
                   native_status='NOT_GENERATED') for i, e in enumerate(optional_block(root, 'device groups'))]
    families, dependencies = {}, {}
    for family, (block, extension, classification, reason) in FAMILIES.items():
        palette = []
        for i, row in enumerate(optional_block(root, block)):
            tag = fixtures.reference(row, 'name', extension)
            palette.append(dict(source_index=i, target_index=None, source_tag=tag,
                                classification=classification, native_status='NOT_GENERATED', reason=reason))
            if tag:
                dependencies.setdefault(tag, dict(source_tag=tag, source_group=extension,
                    source_palette_uses=[], model=None, render_model=None, collision_model=None,
                    physics_model=None, animation_graph=None, materials=[], bitmaps=[], variants=[],
                    functions=[], bounds=None, dependency_provenance=[], status='NOT_DECODED'))['source_palette_uses'].append(
                        dict(family=family, source_index=i))
        placements = [placement(e, family, palette, names, len(selection['bsps']), len(groups))
                      for e in optional_block(root, family)]
        families[family] = dict(palette=palette, placements=placements, source_palette_count=len(palette),
            source_instance_count=len(placements), translated_palette_count=0, translated_instance_count=0,
            deferred_palette_count=len(palette), deferred_instance_count=len(placements))
    relationships = []
    for control in families['controls']['placements']:
        for field in ('position group', 'power group'):
            group = control['device_groups'][field]
            if group < 0:
                continue
            for machine in families['machines']['placements']:
                if machine['device_groups'][field] == group:
                    relationships.append(dict(source_control_index=control['source_index'],
                        source_machine_index=machine['source_index'], group_field=field,
                        source_group_index=group, group_name=groups[group]['name'],
                        evidence='EXACT_SHARED_SOURCE_DEVICE_GROUP', native_status='NOT_GENERATED', runtime_status='NOT_TESTED'))
    result = dict(format='foundry.h3-scenario-translation', version=1,
        source_scenario=selection['source_scenario'], source_sha256=source_sha256, source_xml_sha256=xml_sha256,
        scope='FULL_SCENARIO', source_section_counts=counts, structure=selection,
        object_names=names, device_groups=groups, device_relationships=relationships,
        families=families, object_dependencies=dependencies,
        starting_profiles=[records(e) for e in optional_block(root, 'player starting profile')],
        starting_locations=[records(e) for e in optional_block(root, 'player starting locations')],
        reference_frames=[records(e) for e in optional_block(root, 'reference frames')],
        zone_switch_triggers=[records(e) for e in optional_block(root, 'zone set switch trigger volumes')],
        trigger_volumes=[records(e) for e in optional_block(root, 'trigger volumes')],
        compiled_relationships=dict(source_pvs_count=counts.get('zone set pvs'),
            source_audibility_count=counts.get('zone set audibility'),
            policy='SOURCE_INDEX_PROVENANCE_ONLY_REBUILD_NATIVE_WITH_TOOL'),
        lighting_fidelity='DEFERRED / technically responsive material-power path but no meaningful visible runtime improvement from diagnostic Power25.',
        runtime_status='NOT_TESTED', native_status='NOT_GENERATED')
    result['inventory_sha256'] = stable_hash(result)
    return result

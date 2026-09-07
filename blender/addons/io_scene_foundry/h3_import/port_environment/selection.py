"""Pure source-scenario selection; source BSP indices never become target indices implicitly."""
from . import SOURCE_SCENARIO
from . import fixtures
from .paths import relative


SCENARIO_FIELDS = frozenset({
    'type', 'flags', 'structure bsps', 'structure seams', 'skies', 'zone sets',
    'cutscene flags', 'player starting locations', 'player starting profile',
    'light volumes', 'light volumes palette', 'scenario resources', 'soft ceilings',
})


def index(value):
    return int(value.rsplit(',', 1)[-1])


def optional_block(root, name):
    if not any(e.get('name') == name for e in root):
        return []
    return fixtures.block(root, name)


def select(root, source_scenario=SOURCE_SCENARIO, zone_set=None, spawn_flag=None):
    source_scenario = relative(source_scenario).as_posix()
    if not source_scenario.endswith('.scenario'):
        raise ValueError('Source must be a .scenario tag')
    if (root.get('group') != 'scenario' or
            root.get('id', '').replace('\\', '/') + '.scenario' != source_scenario or
            fixtures.field(root, 'type') != 'solo'):
        raise ValueError('Live source scenario identity/type does not match the requested scenario')
    bsps = fixtures.block(root, 'structure bsps')
    zones = fixtures.block(root, 'zone sets')
    if not 0 < len(bsps) <= 32:
        raise ValueError('Reach environment requires 1..32 source BSP relationships')
    scaffold = not zones and len(bsps) == 1 and source_scenario == SOURCE_SCENARIO and zone_set is None
    if scaffold:
        mask, source_zone_index, zone_name, zone_fields = 1, None, 'proof_box', {}
    else:
        matches = [(i, z) for i, z in enumerate(zones) if fixtures.field(z, 'name') == zone_set]
        if zone_set is None or len(matches) != 1:
            raise ValueError('Select exactly one authored zone set by name; available: ' +
                             ', '.join(fixtures.field(z, 'name', '') for z in zones))
        source_zone_index, zone = matches[0]
        zone_fields = fixtures.fields(zone)
        mask, zone_name = int(fixtures.field(zone, 'bsp zone flags')), zone_set
        if mask <= 0 or mask >> len(bsps):
            raise ValueError('Source zone-set BSP mask is empty or references an absent BSP')
    rows = []
    for i, row in enumerate(bsps):
        if not mask & (1 << i):
            continue
        source_bsp = fixtures.reference(row, 'structure bsp', 'scenario_structure_bsp')
        if not source_bsp:
            raise ValueError(f'Active BSP {i} has no structure BSP reference')
        rows.append(dict(source_index=i, target_index=len(rows), source_tag=source_bsp,
                         structure_design=fixtures.reference(row, 'structure design', 'structure_design'),
                         lighting_info=fixtures.reference(row, 'structure lighting_info', 'scenario_structure_lighting_info'),
                         default_sky=index(fixtures.field(row, 'default sky')),
                         source_fields=fixtures.fields(row)))
    if len({r['source_tag'] for r in rows}) != len(rows):
        raise ValueError('Repeated active source BSP identity needs an explicit placement relationship')
    skies = []
    palette = fixtures.block(root, 'skies')
    for i, row in enumerate(palette):
        activation = int(fixtures.field(row, 'active on bsps'))
        needed = [r for r in rows if r['default_sky'] == i or activation & (1 << r['source_index'])]
        if scaffold:
            needed = rows
        if needed:
            source = fixtures.reference(row, 'sky', 'scenery')
            if source is None:
                raise ValueError(f'Active source sky palette entry {i} is empty')
            skies.append(dict(source_index=i, target_index=len(skies), source_tag=source,
                              source_active_bsp_mask=activation,
                              active_bsp_mask=sum(1 << r['target_index'] for r in needed)))
    for row in rows:
        if row['default_sky'] >= len(palette) or row['default_sky'] < -1:
            raise ValueError(f"BSP {row['source_index']} references an invalid sky index")
        row['target_sky_index'] = next((s['target_index'] for s in skies if s['source_index'] == row['default_sky']),
                                      0 if scaffold else -1)
    spawn = None
    if spawn_flag:
        matches = [r for r in optional_block(root, 'cutscene flags') if fixtures.field(r, 'name') == spawn_flag]
        if len(matches) != 1:
            raise ValueError('Requested source spawn flag is missing or ambiguous: ' + spawn_flag)
        row = matches[0]
        position = [float(v) for v in fixtures.field(row, 'position').split(',')]
        facing = [float(v) for v in fixtures.field(row, 'facing').split(',')]
        from .model import finite
        finite(position, 3); finite(facing, 2)
        spawn = dict(position_world=position, facing_degrees=facing[0], pitch_degrees=facing[1],
                     source_flag=spawn_flag, source_index=int(row.get('index')),
                     classification='GENERATED', strategy='H3 authored cutscene flag -> Reach player starting location')
    return dict(source_scenario=source_scenario, source_zone_set=zone_name, source_zone_index=source_zone_index,
                source_zone_fields=zone_fields, source_bsp_mask=mask,
                target_bsp_mask=(1 << len(rows))-1, bsps=rows, skies=skies, spawn=spawn,
                light_palette=[dict(source_index=i, source_tag=fixtures.reference(row, 'name', 'light'))
                               for i,row in enumerate(optional_block(root, 'light volumes palette'))],
                structure_seams=fixtures.reference(root, 'structure seams', 'structure_seams')
                    if fixtures.field(root, 'structure seams') is not None else None,
                classification='TARGET_DEFAULT' if scaffold else 'GENERATED')

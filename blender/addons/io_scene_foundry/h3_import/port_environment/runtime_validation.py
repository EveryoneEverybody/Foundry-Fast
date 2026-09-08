"""Source-indexed runtime fixtures; build receipts never imply runtime passes."""
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime

from .model import stable_hash


PENDING = 'RUNTIME_TEST_PENDING'
CHECKS = {
    'scenery': ('visible', 'model_material', 'transform', 'variant', 'collision'),
    'crates': ('visible', 'model_material', 'transform', 'collision', 'physical_response'),
    'machines': ('visible', 'transform', 'position_states', 'animation', 'moving_collision'),
    'controls': ('visible', 'transform', 'usable', 'linked_machine_response'),
}


def placement_flags(row):
    field = next((r for r in row['source_records'] if r['name'] == 'placement flags'), None)
    if field is None or (int(field['value']) and not field.get('set_flags')):
        raise ValueError('Source placement requires named flag evidence')
    return list(field.get('set_flags', []))


def spawn_summary(translation):
    result = {}
    for family in CHECKS:
        group = translation['families'][family]
        rows = [r for r in group['placements'] if r['native_status'] == 'NATIVE_AUTHORED_READBACK_VERIFIED']
        manual = [r for r in rows if 'not automatically' in placement_flags(r)]
        result[family] = dict(translated=len(rows), deferred=group['deferred_instance_count'],
            automatic_flag_candidates=len(rows)-len(manual), not_automatically=len(manual),
            named_manual_candidates=sum(bool(r['source_object_name']) for r in manual),
            caveat='Automatic flag eligibility does not establish active zone membership or runtime existence')
    return result


def fixture(translation, objects, family, source_index):
    if family not in CHECKS:
        raise ValueError('Only scenery, crates, machines and controls are runtime fixture families')
    rows = [r for r in translation['families'][family]['placements'] if r['source_index'] == source_index]
    if len(rows) != 1 or rows[0]['native_status'] != 'NATIVE_AUTHORED_READBACK_VERIFIED':
        raise ValueError('Fixture must have one native-readback-verified source placement')
    row = rows[0]
    palettes = [p for p in translation['families'][family]['palette'] if p['source_index'] == row['source_palette_index']]
    if len(palettes) != 1:
        raise ValueError('Fixture palette identity is absent or ambiguous')
    palette = palettes[0]
    compiled = [o for o in objects if o['source_tag'] == palette['source_tag'] and o['status'] == 'NATIVE_COMPILED']
    if len(compiled) != 1 or compiled[0]['target_tag'] != palette['target_tag']:
        raise ValueError('Fixture requires a matching compiled object receipt')
    native = compiled[0]['native_validation']
    if native['status'] != 'NATIVE_DEPENDENCIES_VERIFIED':
        raise ValueError('Fixture native dependencies are unverified')
    fields = ('source_index', 'target_index', 'source_palette_index', 'target_palette_index',
              'source_object_name', 'position_world', 'rotation_degrees', 'scale', 'variant',
              'source_origin_bsp', 'bsp_policy', 'source_manual_bsp_mask', 'device_groups',
              'parent', 'stored_pose_count', 'stored_pose_status', 'classification')
    result = {k: deepcopy(row.get(k)) for k in fields}
    result.update(id=f'{family}:{source_index}', family=family, source_tag=palette['source_tag'],
        target_tag=palette['target_tag'], source_placement_flags=placement_flags(row),
        tool_status='TOOL_COMPILED', native_status='NATIVE_READBACK_VERIFIED',
        native_dependencies=deepcopy(native['chain']), runtime_status=PENDING,
        checks={k: dict(status=PENDING, observations=[]) for k in CHECKS[family]})
    result['spawn_policy'] = ('EXPLICIT_SOURCE_SPAWN_REQUIRED'
        if 'not automatically' in result['source_placement_flags'] else 'AUTOMATIC_FLAG_ELIGIBLE')
    result['relationships'] = [deepcopy(r) for r in translation['compiled_relationships']
        if (family == 'controls' and r['source_control_index'] == source_index)
        or (family == 'machines' and r['source_machine_index'] == source_index)]
    groups = {r['source_group_index'] for r in result['relationships']}
    result['group_authoring'] = [deepcopy(r) for r in translation['device_groups'] if r['source_index'] in groups]
    result['fixture_sha256'] = stable_hash(result)
    return result


def apply_observations(fixtures, observations, scenario_sha256):
    """Bind manual or observed results to the exact fixture and scenario bytes."""
    result = deepcopy(fixtures)
    by_id = {f['id']: f for f in result}
    if len(by_id) != len(result):
        raise ValueError('Duplicate fixture identity')
    seen = set()
    for observation in observations:
        key = (observation['fixture_id'], observation['check'])
        if key in seen:
            raise ValueError('Conflicting/repeated observation; use one explicit result per check per report')
        seen.add(key)
        f = by_id.get(key[0])
        if f is None or key[1] not in f['checks']:
            raise ValueError('Unknown fixture or check')
        if observation['scenario_sha256'] != scenario_sha256 or observation['fixture_sha256'] != f['fixture_sha256']:
            raise ValueError('Runtime observation belongs to different fixture/scenario bytes')
        if observation['basis'] not in ('NATE_MANUAL', 'SUPPORTED_COMPUTER_USE'):
            raise ValueError('Runtime evidence must be manual or directly observed, never a build receipt')
        if observation['status'] not in ('RUNTIME_PASS', 'RUNTIME_FAIL', PENDING):
            raise ValueError('Invalid runtime status')
        if not observation.get('observer', '').strip() or not observation.get('evidence', '').strip():
            raise ValueError('Runtime observation requires an observer and concrete evidence')
        if datetime.fromisoformat(observation['observed_at']).tzinfo is None:
            raise ValueError('Runtime observation requires a timezone')
        f['checks'][key[1]] = dict(status=observation['status'], observations=[deepcopy(observation)])
    for f in result:
        statuses = {r['status'] for r in f['checks'].values()}
        f['runtime_status'] = ('RUNTIME_FAIL' if 'RUNTIME_FAIL' in statuses else
            'RUNTIME_PASS' if statuses == {'RUNTIME_PASS'} else PENDING)
    return result


def blocker_class(reason):
    text = reason.lower()
    for needle, category in (
        ('unambiguous source body association', 'PHYSICS_SHAPE_BODY_ASSOCIATION'),
        ('rigid-body identities differ', 'PHYSICS_BODY_IDENTITY'),
        ('non-positive sphere radius', 'PHYSICS_NONPOSITIVE_RADIUS'),
        ('capsule/constraint', 'PHYSICS_CAPSULE_CONSTRAINT'),
        ('indexed', 'BITMAP_INDEXED_LAYOUT'),
        ('readback differs: misc', 'SHADER_MISC_SEMANTICS'),
        ('cubemap', 'BITMAP_CUBEMAP_READBACK'),
        ('runtime functions/externs', 'SHADER_FUNCTIONS_EXTERNS'),
        ('rmhg', 'SHADER_HALOGRAM'), ('rmct', 'SHADER_CORTANA'),
        ('insufficient', 'PHYSICS_INSUFFICIENT_SHAPES'),
        ('spec_tint_map', 'SHADER_MCC_PBR'),
        ('cannot find', 'SOURCE_FILE_ABSENT'), ('no such file', 'SOURCE_FILE_ABSENT'),
    ):
        if needle in text:
            return category
    return 'OTHER_EXACT_REASON_RETAINED'


def blocker_yield(translation, blockers):
    """Count affected placements once per source root, retaining every exact reason."""
    weights = Counter()
    for family in CHECKS:
        group = translation['families'][family]
        palette = {r['source_index']: r['source_tag'] for r in group['palette']}
        for row in group['placements']:
            if row['source_palette_index'] in palette:
                weights[palette[row['source_palette_index']]] += 1
    groups = defaultdict(list)
    seen = set()
    for row in blockers:
        if row['source_tag'] in seen:
            raise ValueError('Duplicate unresolved object root')
        seen.add(row['source_tag'])
        reason = row['reason'] if isinstance(row['reason'], str) else '; '.join(row['reason'])
        groups[blocker_class(reason)].append(dict(source_tag=row['source_tag'], stage=row['stage'],
            exact_reason=deepcopy(row['reason']), affected_source_placements=weights[row['source_tag']]))
    result = [dict(category=k, roots=sorted(v, key=lambda r: (-r['affected_source_placements'], r['source_tag'])),
        root_count=len(v), affected_source_placements=sum(r['affected_source_placements'] for r in v),
        interpretation='Potential source population; other blockers, parents and runtime spawn policy may still defer it')
        for k, v in groups.items()]
    return sorted(result, key=lambda r: (-r['affected_source_placements'], r['category']))

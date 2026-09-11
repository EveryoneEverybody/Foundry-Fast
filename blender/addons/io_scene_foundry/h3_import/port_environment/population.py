"""Pure append/update reconciliation for an existing native scenario.

No source table index is a target identity. Unowned placements are only adopted
when a unique source ID, native root and complete authoring comparison agree.
The native adapter supplies that comparison and an immutable target snapshot.
"""
from copy import deepcopy

from .model import stable_hash
from .native_placements import SUPPORTED

MODE = 'POPULATE_EXISTING_SCENARIO'


def canonical(path):
    return path.replace('\\', '/').lower()


def logical_id(source, family, index):
    return canonical(source) + ':' + family + ':' + str(index)


def unique(rows, predicate, label):
    found = [i for i, row in enumerate(rows) if predicate(row)]
    if len(found) > 1:
        raise ValueError('Ambiguous ' + label)
    return found[0] if found else None


def reconcile(translation, target, *, families=SUPPORTED, provenance=None,
              equivalent=None):
    """Plan atomically per placement; preserve every existing table entry.

    Target rows contain native identity plus a native authoring fingerprint.
    ``equivalent`` must compare every field the placement writer would author;
    default equality is useful for detached, normalized native snapshots.
    Provenance is accepted only when its target fingerprint still agrees.
    """
    families = tuple(families)
    if not families or len(set(families)) != len(families) or set(families)-set(SUPPORTED):
        raise ValueError('Select distinct supported population families')
    provenance = provenance or {}
    equivalent = equivalent or (lambda native, source: native['semantic'] == source['semantic'])
    state = deepcopy(target)
    result = dict(mode=MODE, source_scenario=translation['source_scenario'],
                  source_sha256=translation['source_sha256'], families=list(families),
                  palette_maps={f: {} for f in families}, object_name_map={},
                  device_group_map={}, placements=[], deferred=[], mutations=[],
                  runtime_status='NOT_TESTED')
    source_names = {r['source_index']: r for r in translation['object_names']}
    source_groups = {r['source_index']: r for r in translation['device_groups']}
    pending = []
    for family in families:
        for row in translation['families'][family]['placements']:
            if row['native_status'] != 'READY':
                result['deferred'].append(dict(family=family, source_index=row['source_index'],
                                               reason=row.get('reason', 'Source dependency deferred')))
            else:
                pending.append(deepcopy(row))
    named = {}
    for row in pending:
        ni = row['source_object_name_index']
        if ni >= 0:
            named.setdefault(ni, []).append(row)
    completed_names = set()
    claimed_targets = set()
    while pending:
        progressed = False
        for original in pending[:]:
            parent = original['parent']['source_name_index']
            if parent >= 0 and parent not in completed_names:
                continue
            pending.remove(original)
            progressed = True
            candidate = deepcopy(state)
            staged = []
            row = deepcopy(original)
            f = row['family']
            identity = logical_id(translation['source_scenario'], f, row['source_index'])
            try:
                ni = row['source_object_name_index']
                if ni >= 0 and len(named[ni]) != 1:
                    raise ValueError('Ambiguous source object name ownership')
                source_palette = next(p for p in translation['families'][f]['palette']
                                      if p['source_index'] == row['source_palette_index'])
                root = canonical(source_palette['target_tag'])
                palette = candidate['families'][f]['palette']
                pi = unique(palette, lambda p: canonical(p['target_tag']) == root, 'target palette identity')
                if pi is None:
                    pi = len(palette)
                    palette.append(dict(target_tag=root))
                    staged.append(dict(table='palette', family=f, index=pi, target_tag=root))
                row['target_palette_index'] = pi
                existing = candidate['families'][f]['placements']
                prior = provenance.get(identity)
                if prior:
                    ti = prior['target_index']
                    if prior['family'] != f or not 0 <= ti < len(existing):
                        raise ValueError('Prior placement target identity is absent')
                    if existing[ti]['fingerprint'] != prior['target_fingerprint']:
                        raise ValueError('Owned target placement changed outside population')
                    if canonical(existing[ti]['target_tag']) != root:
                        raise ValueError('Owned target placement root differs')
                else:
                    uid = row.get('unique_id')
                    valid_uid = uid is not None and str(uid) not in {'', '-1', '0', '4294967295'}
                    if not valid_uid and any(canonical(r['target_tag']) == root for r in existing):
                        raise ValueError('Existing root lacks unambiguous source placement provenance')
                    matches = [i for i, r in enumerate(existing)
                               if valid_uid and str(r.get('unique_id')) == str(uid)]
                    if len(matches) > 1:
                        raise ValueError('Ambiguous preexisting source unique ID; preserve unowned placements')
                    ti = matches[0] if matches else None
                    if ti is not None and canonical(existing[ti]['target_tag']) != root:
                        raise ValueError('Preexisting source unique ID has a different root')
                row['target_index'] = len(existing) if ti is None else ti
                if (f,row['target_index']) in claimed_targets:
                    raise ValueError('Multiple source placements claim the same target identity')
                row['target_object_name_index'] = -1
                if ni >= 0:
                    name = source_names[ni]['name']
                    names = candidate['object_names']
                    target_name = unique(names, lambda n: n['name'] == name, 'target object name')
                    if target_name is None:
                        target_name = len(names)
                        names.append(dict(name=name, uses=[]))
                        staged.append(dict(table='object_names', index=target_name, name=name))
                    allowed = dict(family=f, index=row['target_index'])
                    if any(use != allowed for use in names[target_name]['uses']):
                        raise ValueError('Existing object name belongs to another placement: ' + name)
                    names[target_name]['uses'] = [allowed]
                    row['target_object_name_index'] = target_name
                row['target_parent_name_index'] = result['object_name_map'][parent] if parent >= 0 else -1
                row['target_device_groups'] = {}
                for field, source_index in row.get('device_groups', {}).items():
                    if source_index < 0:
                        row['target_device_groups'][field] = -1
                        continue
                    source = source_groups[source_index]
                    groups = candidate['device_groups']
                    gi = unique(groups, lambda g: g['name'] == source['name'], 'target device group')
                    if gi is None:
                        gi = len(groups)
                        groups.append(deepcopy(source))
                        staged.append(dict(table='device_groups', index=gi, source_index=source_index))
                    elif groups[gi]['semantic'] != source['semantic']:
                        raise ValueError('Existing device group semantics differ: ' + source['name'])
                    row['target_device_groups'][field] = gi
                equal = ti is not None and equivalent(existing[ti], row)
                if ti is not None and not prior and not equal:
                    raise ValueError('Unowned unique-ID match has different authoring; preserve existing placement')
                action = 'UNCHANGED' if equal else 'APPEND' if ti is None else 'UPDATE'
                row.update(action=action, logical_id=identity,
                           ownership_basis='PRIOR_PROVENANCE' if prior else 'UNIQUE_ID_ROOT_AND_AUTHORING' if equal else 'NEW')
                if action != 'UNCHANGED':
                    staged.append(dict(table='placements', family=f, index=row['target_index'], action=action))
                if ti is None:
                    existing.append(dict(target_tag=root, unique_id=row.get('unique_id'),
                                         fingerprint=None, semantic=row.get('semantic')))
                state = candidate
                result['mutations'].extend(staged)
                result['placements'].append(row)
                claimed_targets.add((f,row['target_index']))
                result['palette_maps'][f][row['source_palette_index']] = pi
                if ni >= 0:
                    result['object_name_map'][ni] = row['target_object_name_index']
                    completed_names.add(ni)
                for field, si in row.get('device_groups', {}).items():
                    if si >= 0:
                        result['device_group_map'][si] = row['target_device_groups'][field]
            except ValueError as exc:
                result['deferred'].append(dict(family=f, source_index=row['source_index'], reason=str(exc)))
        if not progressed:
            result['deferred'].extend(dict(family=r['family'], source_index=r['source_index'],
                reason='Parent placement deferred, outside selected families, or cyclic') for r in pending)
            break
    result['semantic_mutation_count'] = len(result['mutations'])
    result['plan_sha256'] = stable_hash(result)
    return result

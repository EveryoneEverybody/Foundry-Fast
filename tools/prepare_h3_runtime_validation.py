"""Prepare read-only runtime fixtures from a completed native scenario handoff."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment.paths import OutputPaths, atomic_json, digest
from port_environment.model import stable_hash
from port_environment import runtime_validation as runtime


def read_evidence(row):
    path = Path(row['path'])
    if digest(path) != row['sha256']:
        raise ValueError('Handoff evidence changed: '+str(path))
    return json.loads(path.read_text(encoding='utf-8'))


def markdown(report):
    lines = ['# Native scenario runtime fixtures', '',
        'These are individual fixture results. Native compilation and readback never establish runtime acceptance.', '',
        '```text', report['game_start'], '```', '',
        '| Family | Translated | Deferred | Automatic flag candidates | Not automatically |',
        '|---|---:|---:|---:|---:|']
    for name, row in report['spawn_summary'].items():
        lines.append(f"| {name} | {row['translated']} | {row['deferred']} | {row['automatic_flag_candidates']} | {row['not_automatically']} |")
    lines += ['', 'An automatic flag candidate can still depend on zone/designer-zone state. Explicit-spawn placements retain the source policy; absent HSC is not a reason to clear flags globally.']
    for f in report['fixtures']:
        lines += ['', f"## {f['id']} — {f['source_object_name'] or Path(f['source_tag']).stem}", '',
            f"Source `{f['source_tag']}` → native `{f['target_tag']}`.", '',
            f"Placement {f['source_index']} → {f['target_index']}; palette {f['source_palette_index']} → {f['target_palette_index']}.", '',
            f"Position `{f['position_world']}`; Euler degrees `{f['rotation_degrees']}`; scale `{f['scale']}`; variant `{f['variant']}`.", '',
            f"Spawn policy `{f['spawn_policy']}`; source BSP `{f['source_origin_bsp']}`; source flags `{f['source_placement_flags']}`.", '',
            f"Stored pose: `{f['stored_pose_status']}`. Native: `{f['tool_status']}`, `{f['native_status']}`. Runtime: **{f['runtime_status']}**.", '',
            '| Check | Runtime status | Evidence |', '|---|---|---|']
        for check, row in f['checks'].items():
            evidence = ' / '.join(o['evidence'].replace('|', '\\|').replace('\n', ' ') for o in row['observations'])
            lines.append(f"| {check} | {row['status']} | {evidence} |")
        for rel in f['relationships']:
            lines += ['', f"Shared source {rel['group_field']} {rel['source_group_index']} (`{rel['group_name']}`): control {rel['source_control_index']} → machine {rel['source_machine_index']}; native control {rel['target_control_index']} → machine {rel['target_machine_index']}."]
        for group in f['group_authoring']:
            flags = [r.get('set_flags', []) for r in group['source_records'] if r['name'] == 'flags']
            lines += ['', f"Group {group['source_index']} initial value `{group['initial_value']}`; flags `{flags}`. Reset the scenario before repeating a one-change group test."]
    lines += ['', '## Reusable blocker populations', '',
        'Potential affected placements are not guaranteed unlocks; exact per-root reasons remain in JSON.', '',
        '| Class | Roots | Source placements |', '|---|---:|---:|']
    lines += [f"| {r['category']} | {r['root_count']} | {r['affected_source_placements']} |" for r in report['blockers']]
    return '\n'.join(lines)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('handoff', 'h3-root', 'reach-root', 'output'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--fixture', action='append', required=True, help='family:source_index; repeat for each fixture')
    parser.add_argument('--observations', help='Explicit per-check observations bound to fixture/scenario hashes')
    args = parser.parse_args()
    handoff = json.loads(Path(args.handoff).read_text(encoding='utf-8'))
    paths = OutputPaths(args.h3_root, args.reach_root, handoff['target']['namespace'], allow_nested=True)
    output = Path(args.output).resolve()
    if output.exists() or output.is_relative_to(paths.h3) or output.is_relative_to(paths.reach):
        raise ValueError('Use a new report directory outside both kits')
    evidence = handoff['evidence']
    translation = read_evidence(evidence['scenario_translation'])
    objects = read_evidence(evidence['native_objects'])
    scenario_receipt = read_evidence(evidence['native_scenario'])
    if objects['status'] != 'COMPLETE' or scenario_receipt['status'] != 'COMPLETE':
        raise ValueError('A completed native build receipt is required')
    if digest(paths.h3_tags/translation['source_scenario']) != translation['source_sha256']:
        raise ValueError('Source scenario changed since inventory')
    # Pin all installed native tags in the final scenario receipt, including
    # generated shader infrastructure. Do not re-own or rewrite any kit files.
    tags = []
    for row in scenario_receipt['generated_files']:
        if not row['path'].replace('\\', '/').startswith('tags/'):
            continue
        file = (paths.reach/row['path']).resolve()
        if not file.is_relative_to(paths.roots['tags']) or digest(file) != row['sha256']:
            raise ValueError('Installed native tag differs from receipt: '+str(file))
        tags.append(dict(path=row['path'], sha256=row['sha256']))
    scenario_hash = digest(paths.owned_tag(paths.scenario+'.scenario'))
    fixtures = []
    for request in args.fixture:
        family, source_index = request.split(':')
        f = runtime.fixture(translation, objects['worker']['objects'], family, int(source_index))
        f['installation_sha256'] = stable_hash(tags)
        f['fixture_sha256'] = stable_hash({k:v for k,v in f.items() if k != 'fixture_sha256'})
        fixtures.append(f)
    observations = json.loads(Path(args.observations).read_text(encoding='utf-8')) if args.observations else []
    fixtures = runtime.apply_observations(fixtures, observations, scenario_hash)
    report = dict(format='foundry.h3-runtime-validation', version=1,
        created_at=datetime.now(timezone.utc).isoformat(),
        handoff=dict(path=str(Path(args.handoff).resolve()), sha256=digest(args.handoff)),
        evidence={k:evidence[k] for k in ('scenario_translation', 'native_objects', 'native_scenario')},
        scenario_sha256=scenario_hash, installed_tag_count=len(tags), installation_sha256=stable_hash(tags),
        game_start='game_start '+paths.scenario.replace('/', '\\'),
        spawn_summary=runtime.spawn_summary(translation), fixtures=fixtures,
        blockers=runtime.blocker_yield(translation, handoff['blockers']['object_roots']),
        scope='Per fixture and per check only; no global family, BSP, physics or transition acceptance')
    output.mkdir(parents=True)
    atomic_json(output/'runtime-validation.json', report)
    (output/'runtime-validation.md').write_text(markdown(report), encoding='utf-8')
    template = [dict(fixture_id=f['id'], fixture_sha256=f['fixture_sha256'], scenario_sha256=scenario_hash,
        check=check, status=runtime.PENDING, basis='NATE_MANUAL', observer='', observed_at='', evidence='')
        for f in fixtures for check in f['checks']]
    atomic_json(output/'observations.template.json', template)
    print(json.dumps(dict(fixtures=len(fixtures), installed_tags=len(tags), report=str(output/'runtime-validation.md'))))


if __name__ == '__main__':
    main()

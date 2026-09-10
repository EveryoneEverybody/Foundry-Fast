"""Create or remove an isolated player-start fixture without rebuilding its map.

Prepare runs inside background Blender. Restore runs in ordinary Python and
removes only the exact scenario file recorded in the completed manifest.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry/h3_import'))
from port_environment.paths import OutputPaths, atomic_json, digest, relative
from port_environment import fixtures


def xml_sections(root):
    """Keep repeated names and ordering in flattened Foundation XML."""
    result = []
    for child in root:
        if child.tag != 'element':
            result.append([child.get('name'), []])
        if not result:
            raise ValueError('Unexpected unowned XML element')
        result[-1][1].append(ET.tostring(child, encoding='unicode').strip())
    return result


def verify_difference(before, after):
    if ({k: v for k, v in before.attrib.items() if k != 'id'} !=
            {k: v for k, v in after.attrib.items() if k != 'id'}):
        raise ValueError('Scenario root metadata changed')
    left, right = xml_sections(before), xml_sections(after)
    if len(left) != len(right):
        raise ValueError('Scenario schema changed')
    differences = []
    for index, (old, new) in enumerate(zip(left, right)):
        if old[0] != new[0]:
            raise ValueError('Scenario field order changed')
        if old != new:
            if old[0] not in {'player starting locations', 'cutscene flags'}:
                raise ValueError('Unexpected scenario change: ' + str(old[0]))
            differences.append(dict(section=index, name=old[0], before=old[1], after=new[1]))
    if {row['name'] for row in differences} != {'player starting locations', 'cutscene flags'}:
        raise ValueError('Expected start and flag changes were not persisted')
    return differences


def export_xml(reach, identity, output, report):
    command = [str(reach / 'tool.exe'), 'export-tag-to-xml', str(reach / 'tags' / relative(identity)), str(output)]
    result = subprocess.run(command, cwd=reach, capture_output=True, text=True, errors='replace')
    log = output.with_suffix('.log')
    log.write_text(result.stdout + result.stderr, encoding='utf-8')
    report.setdefault('commands', []).append(dict(argv=command, cwd=str(reach), exit_code=result.returncode, log=str(log)))
    if result.returncode or not output.is_file() or not output.stat().st_size:
        raise RuntimeError('Read-only native XML export failed; see ' + str(log))
    return fixtures.parse(output.read_bytes())


def check_vector(actual, expected, name):
    actual = list(actual)
    if len(actual) != len(expected) or any(not math.isfinite(a) or not math.isfinite(b) or
                                         abs(a - b) > 1e-5 for a, b in zip(actual, expected)):
        raise ValueError('Native transform differs: ' + name)


def verify_poses(before, after, spec):
    """Check exact requested poses and retain every unrelated start/flag field."""
    def numbers(element, name):
        return [float(value) for value in fixtures.field(element, name).split(',')]

    original = fixtures.block(before, 'player starting locations')
    native = fixtures.block(after, 'player starting locations')
    if not original or len(original) != len(native):
        raise ValueError('Player start count changed or no player starts exist')
    start = next(row for row in spec['flags'] if row['name'] == spec['initial_flag'])
    for old, new in zip(original, native):
        for name, expected in [('position', start['position']), ('facing', [start['facing_degrees']]),
                               ('pitch', [start.get('pitch_degrees', 0)])]:
            check_vector(numbers(new, name), expected, 'player start ' + name)
        restored = deepcopy(new)
        for element in restored:
            if element.get('name') in ('position', 'facing', 'pitch'):
                element.set('value', fixtures.field(old, element.get('name')))
        if ET.tostring(old).strip() != ET.tostring(restored).strip():
            raise ValueError('Player start profile changed beyond its pose')
    original = fixtures.block(before, 'cutscene flags')
    native = fixtures.block(after, 'cutscene flags')
    if len(native) != len(original) + len(spec['flags']):
        raise ValueError('Unexpected diagnostic flag count')
    for old, new in zip(original, native):
        if ET.tostring(old).strip() != ET.tostring(new).strip():
            raise ValueError('Existing cutscene flag changed')
    for row, new in zip(spec['flags'], native[len(original):]):
        if fixtures.field(new, 'name') != row['name']:
            raise ValueError('Diagnostic flag name changed')
        check_vector(numbers(new, 'position'), row['position'], row['name'])
        check_vector(numbers(new, 'facing'), [row['facing_degrees'], row.get('pitch_degrees', 0)], row['name'])


def runtime_setup(spec, h3, before):
    """Emit only individually reviewed, exact source kill-volume startup calls.

    This is a console checklist, not script conversion or HSC execution. The
    selected call's source bytes/line and native volume identity must still match.
    It must run after loading at a safe start, before teleporting into the volume.
    """
    commands, seen = [], set()
    native_names = [fixtures.field(e, 'name') for e in fixtures.block(before, 'trigger volumes')]
    data = (h3 / 'data').resolve(strict=True)
    for row in spec.get('disabled_kill_volumes', []):
        name = row['name']
        if not re.fullmatch(r'[a-zA-Z0-9_]+', name) or name in seen or native_names.count(name) != 1:
            raise ValueError('Missing, repeated, or invalid startup kill volume: ' + name)
        path = (data / relative(row['source_script'])).resolve(strict=True)
        if not path.is_relative_to(data) or path.suffix != '.hsc' or digest(path) != row['source_sha256']:
            raise ValueError('Source startup script changed or escaped H3 data')
        lines = path.read_bytes().splitlines()
        number = row['source_line']
        expected = '(kill_volume_disable ' + name + ')'
        if not isinstance(number, int) or number < 1 or number > len(lines) or lines[number - 1].strip() != expected.encode('ascii'):
            raise ValueError('Source startup call differs at the selected line')
        seen.add(name)
        commands.append(expected)
    return commands


def preserve_native_derived_fields(tag, before):
    """Undo native load defaults before saving an otherwise unchanged copy.

    ManagedBlam clears object-name reverse indices and seeds box trigger sector
    points when loading this scenario. Reconstruct indices from the unchanged
    forward placements, and retain the original empty sector authoring. The
    complete XML comparison below still rejects any difference in these blocks.
    """
    names = tag.tag.SelectField('object names').Elements
    for family in ('scenery', 'crates', 'machines', 'controls'):
        for element in tag.tag.SelectField(family).Elements:
            index = int(element.SelectField('name').Value)
            if index >= 0:
                names[index].SelectField('object_type').Value = int(element.SelectField('object data[0]/object id[0]/type').Value)
                names[index].SelectField('scenario_datum_index').Value = element.ElementIndex
    original = fixtures.block(before, 'trigger volumes')
    native = tag.tag.SelectField('trigger volumes').Elements
    if len(original) != native.Count:
        raise ValueError('Trigger count changed during native load')
    for source, element in zip(original, native):
        if not fixtures.block(source, 'sector points'):
            element.SelectField('sector points').RemoveAllElements()
        element.SelectField('C').Data = float(fixtures.field(source, 'C'))


def prepare(args):
    spec_path = Path(args.spec).resolve(strict=True)
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    paths = OutputPaths(args.h3_root, args.reach_root, args.namespace, allow_nested=True)
    main_relative = relative(spec['main_scenario']).as_posix()
    main = (paths.roots['tags'] / main_relative).resolve(strict=True)
    if not main.is_relative_to(paths.roots['tags']) or main.suffix != '.scenario':
        raise ValueError('Main scenario must be an existing Reach scenario')
    target = paths.owned_tag(paths.scenario + '.scenario')
    if main == target or main.is_relative_to(paths.destination('tags')):
        raise ValueError('Fixture must have an independent namespace')
    if digest(main) != spec['main_sha256']:
        raise ValueError('Main scenario changed since fixture selection')
    output = Path(args.output).resolve()
    if output.exists() or any(output.is_relative_to(root) for root in (paths.reach, paths.h3)):
        raise ValueError('Use a fresh report directory outside both kits')
    if paths.destination('tags').exists() or paths.destination('data').exists():
        raise ValueError('Fixture namespace already exists; use a fresh namespace')
    flags = spec['flags']
    names = [row['name'] for row in flags]
    if len(names) != len(set(names)) or spec['initial_flag'] not in names:
        raise ValueError('Fixture flags require unique names and an explicit initial flag')
    for row in flags:
        if not re.fullmatch(r'[a-zA-Z0-9_]{1,31}', row['name']) or not row.get('basis', '').strip():
            raise ValueError('Diagnostic flag requires a safe name and a placement basis')
        if len(row['position']) != 3:
            raise ValueError('Diagnostic flag position requires three coordinates')
        check_vector(row['position'] + [row['facing_degrees'], row.get('pitch_degrees', 0)],
                     row['position'] + [row['facing_degrees'], row.get('pitch_degrees', 0)], row['name'])
    output.mkdir(parents=True, exist_ok=False)
    report = dict(format='foundry.h3-player-interaction-fixture', version=1, status='PREPARING',
        created_at=datetime.now(timezone.utc).isoformat(), spec_path=str(spec_path), spec_sha256=digest(spec_path),
        spec=spec, h3_root=str(paths.h3), reach_root=str(paths.reach), namespace=paths.namespace,
        main_scenario=str(main), main_sha256=digest(main), fixture_scenario=str(target),
        runtime_status='RUNTIME_TEST_PENDING')
    atomic_json(output / 'creation-intent.json', report)
    shutil.copyfile(main, output / 'main-before.scenario')
    before = export_xml(paths.reach, main_relative, output / 'main-before.xml', report)
    report['after_load_commands'] = runtime_setup(spec, paths.h3, before)
    zones = [fixtures.field(e, 'name') for e in fixtures.block(before, 'zone sets')]
    if zones.count(spec['initial_zone']) != 1:
        raise ValueError('Initial zone is missing or ambiguous')
    report['flag_commands'] = {}
    for row in flags:
        if 'zone' in row:
            if zones.count(row['zone']) != 1:
                raise ValueError('Diagnostic flag zone is missing or ambiguous')
            report['flag_commands'][row['name']] = ['switch_zone_set ' + row['zone'],
                '(object_teleport (list_get (players) 0) ' + row['name'] + ')']
    from port_environment import object_worker
    object_worker.bootstrap(paths, output, report)
    from io_scene_foundry.managed_blam import Tag
    with Tag(path=main_relative, tag_must_exist=True) as tag:
        for row in spec['anchors']:
            element = tag.tag.SelectField(row['family']).Elements[row['native_index']]
            actual = element.SelectField('object data[0]/position').Data
            check_vector(actual, row['position'], row['id'])
    target.parent.mkdir(parents=True, exist_ok=False)
    with target.open('xb') as stream:
        stream.write(main.read_bytes())
    with Tag(path=paths.scenario + '.scenario', tag_must_exist=True) as tag:
        block = tag.tag.SelectField('cutscene flags')
        existing = {e.SelectField('name').GetStringData() for e in block.Elements}
        if existing.intersection(names):
            raise ValueError('Diagnostic flag conflicts with existing source flag')
        for row in flags:
            element = block.AddElement()
            element.SelectField('name').SetStringData(row['name'])
            element.SelectField('position').Data = row['position']
            element.SelectField('facing').Data = [row['facing_degrees'], row.get('pitch_degrees', 0)]
        start = next(row for row in flags if row['name'] == spec['initial_flag'])
        starts = tag.tag.SelectField('player starting locations')
        # Preserve all four native start profiles; only their pose changes.
        for element in starts.Elements:
            element.SelectField('position').Data = start['position']
            element.SelectField('facing').Data = start['facing_degrees']
            element.SelectField('pitch').Data = start.get('pitch_degrees', 0)
        preserve_native_derived_fields(tag, before)
        tag.tag_has_changes = True
    after = export_xml(paths.reach, paths.scenario + '.scenario', output / 'fixture-after.xml', report)
    report['differences'] = verify_difference(before, after)
    verify_poses(before, after, spec)
    report['preserved_counts'] = {name:len(fixtures.block(after, name)) for name in
        ('structure bsps', 'zone sets', 'scenery', 'crates', 'machines', 'controls')}
    if digest(main) != spec['main_sha256']:
        raise ValueError('Main scenario preservation check failed')
    report.update(status='NATIVE_READBACK_VERIFIED', fixture_sha256=digest(target),
        launch_commands=['game_initial_zone_set ' + spec['initial_zone'],
            'game_start ' + paths.scenario.replace('/', '\\')])
    shutil.copyfile(target, output / 'fixture-verified.scenario')
    atomic_json(output / 'fixture-manifest.json', report)
    print(json.dumps({key:report[key] for key in ('status', 'fixture_sha256', 'preserved_counts', 'launch_commands')}, indent=2))


def restore(manifest_path):
    manifest_path = Path(manifest_path).resolve(strict=True)
    report = json.loads(manifest_path.read_text(encoding='utf-8'))
    if report.get('format') != 'foundry.h3-player-interaction-fixture' or report.get('status') != 'NATIVE_READBACK_VERIFIED':
        raise ValueError('A completed fixture manifest is required')
    paths = OutputPaths(report['h3_root'], report['reach_root'], report['namespace'], allow_nested=True)
    target = paths.owned_tag(paths.scenario + '.scenario')
    if str(target) != report['fixture_scenario'] or digest(target) != report['fixture_sha256']:
        raise ValueError('Fixture changed; refusing cleanup')
    if digest(report['main_scenario']) != report['main_sha256']:
        raise ValueError('Main scenario changed; refusing cleanup')
    receipt = manifest_path.parent / 'restore-receipt.json'
    if receipt.exists():
        raise ValueError('Restore receipt already exists')
    target.unlink()
    # No recursive removal: keep any unrecognized files for explicit review.
    if not list(target.parent.iterdir()):
        target.parent.rmdir()
    atomic_json(receipt, dict(status='RESTORED', restored_at=datetime.now(timezone.utc).isoformat(),
        removed=str(target), removed_sha256=report['fixture_sha256'], main_sha256=digest(report['main_scenario'])))
    print(str(receipt))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore', metavar='MANIFEST')
    for name in ('spec', 'h3-root', 'reach-root', 'namespace', 'output'):
        parser.add_argument('--' + name)
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else None
    args = parser.parse_args(argv)
    if args.restore:
        restore(args.restore)
    else:
        if not all(getattr(args, name) for name in ('spec', 'h3_root', 'reach_root', 'namespace', 'output')):
            parser.error('Prepare requires --spec, --h3-root, --reach-root, --namespace and --output')
        prepare(args)


if __name__ == '__main__':
    main()

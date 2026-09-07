"""Read both nested H3 Tool XML and flattened Reach Foundation XML as evidence.

XML fields are data. No embedded command, code, resource payload or runtime block
is executed or copied into a target tag.
"""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from .paths import relative


def parse(content):
    if len(content) > 32 * 1024 * 1024 or b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
        raise ValueError('Unsupported XML size or entity declarations')
    # H3 Tool writes the null group tag 0xffffffff verbatim in an otherwise
    # UTF-8 XML attribute. Normalize only that exact null-reference sentinel;
    # unexpected invalid bytes still fail XML parsing. Hash the original bytes.
    content = content.replace(b',\xff\xff\xff\xff" type="tag reference"',
                              b',NULL" type="tag reference"')
    content = content.replace(b'value="<unavailable>" type="pageable resource"',
                              b'value="&lt;unavailable&gt;" type="pageable resource"')
    root = ET.fromstring(content)
    if root.tag != 'tag':
        raise ValueError('Expected a Tool/Foundation tag XML export')
    return root


def field(node, name, default=None):
    matches = [e for e in node if e.tag == 'field' and e.get('name') == name]
    if len(matches) > 1:
        raise ValueError('Ambiguous XML field: ' + name)
    return matches[0].get('value') if matches else default


def block(node, name):
    children = list(node)
    matches = [e for e in children if e.get('name') == name and
               (e.tag == 'block' or (e.tag == 'field' and e.get('type') == 'block'))]
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous XML block: ' + name)
    marker = matches[0]
    if marker.tag == 'block':
        result = list(marker.findall('element'))
        expected = int(marker.get('value').rsplit(',', 1)[-1])
    else:
        result = []
        for e in children[children.index(marker) + 1:]:
            if e.tag != 'element':
                break
            result.append(e)
        expected = int(marker.get('value'))
    if len(result) != expected or [int(e.get('index')) for e in result] != list(range(expected)):
        raise ValueError('XML element count/index mismatch: ' + name)
    return result


def fields(node):
    return {e.get('name'): e.get('value') for e in node if e.tag == 'field' and
            e.get('type') not in {'block', 'struct', 'pad', 'skip', 'data', 'array'}}


def reference(node, name, extension):
    value = field(node, name)
    if value is None:
        raise ValueError('Missing H3 reference: ' + name)
    path = value.split(',', 1)[0]
    return (relative(path).as_posix() + '.' + extension) if path else None


def scenario_semantics(root):
    if root.get('group') != 'scenario':
        raise ValueError('Not a scenario fixture')
    return dict(identity=root.get('id').replace('\\', '/'), type=field(root, 'type'),
                bsps=[fields(e) for e in block(root, 'structure bsps')],
                skies=[fields(e) for e in block(root, 'skies')],
                player_starts=[fields(e) for e in block(root, 'player starting locations')],
                player_profiles=[fields(e) for e in block(root, 'player starting profile')],
                zone_sets=[fields(e) for e in block(root, 'zone sets')],
                has_top_level_designs=any(e.get('name') == 'structure designs' for e in root))


def lighting_semantics(root):
    if root.get('group') != 'scenario_structure_lighting_info':
        raise ValueError('Not a lighting-info fixture')
    return dict(materials=[fields(e) for e in block(root, 'material info')],
                light_definitions=[fields(e) for e in block(root, 'generic light definitions')],
                light_instances=[fields(e) for e in block(root, 'generic light instances')])


def validate_archive(path):
    with ZipFile(path) as archive:
        if len(archive.infolist()) > 64 or len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError('Invalid fixture archive member table')
        for entry in archive.infolist():
            relative(entry.filename.rstrip('/'))
            if entry.file_size > 32 * 1024 * 1024:
                raise ValueError('Oversized fixture archive member')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('format') != 'foundry.h3-reach-box-fixtures' or manifest.get('version') != 1:
            raise ValueError('Unsupported paired fixture manifest')
        tags, hashes = {}, {}
        for row in manifest['files']:
            name = relative(row['game'] + '/' + row['path']).as_posix()
            if name in tags:
                raise ValueError('Duplicate fixture identity')
            content = archive.read(name)
            sha = hashlib.sha256(content).hexdigest()
            if len(content) != row['bytes'] or sha != row['sha256']:
                raise ValueError('Fixture manifest hash mismatch: ' + name)
            try:
                tags[name] = parse(content)
            except (ValueError, ET.ParseError) as exc:
                raise ValueError(f'{name}: {exc}') from exc
            hashes[name] = sha
    return dict(format='foundry.h3-reach-box-fixture-validation', version=1,
                files=hashes, h3=scenario_semantics(tags['h3/box.scenario.xml']),
                reach=scenario_semantics(tags['reach/box.scenario.xml']),
                h3_lighting=lighting_semantics(tags['h3/box.scenario_structure_lighting_info.xml']),
                reach_lighting=lighting_semantics(tags['reach/box_000.scenario_structure_lighting_info.xml']),
                limitations=['Reach Foundation references are display names, not authoritative full paths.',
                             'Paired fixtures are semantic evidence; runtime/resources are never templates.'])

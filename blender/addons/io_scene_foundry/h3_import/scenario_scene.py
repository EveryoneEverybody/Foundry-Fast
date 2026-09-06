"""Validate detached BSP geometry and resolve authored H3 hint references."""
from collections import defaultdict
import json
import math
from pathlib import Path
import re

from . import scenario_inspection as inspection

MAX_GEOMETRY_BYTES = 512 * 1024 * 1024
GEOMETRY_PATH = re.compile(r'geometry/bsp_[0-9]{4,}\.json\Z')


def integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError('Expected an integer in range')
    return value


def numbers(value, size):
    if not isinstance(value, list) or len(value) != size:
        raise ValueError(f'Expected {size} numeric components')
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
        raise ValueError('Nonfinite or invalid numeric component')
    return value


def checked_json(path, limit=MAX_GEOMETRY_BYTES):
    path = Path(path)
    if path.stat().st_size > limit:
        raise ValueError('Source manifest exceeds the byte limit')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Nonfinite JSON number: ' + value)
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs, parse_constant=constant)


def within(directory, relative):
    relative = inspection.relative_path(relative)
    root = Path(directory).resolve(strict=True)
    result = (root / relative).resolve(strict=True)
    if not result.is_relative_to(root) or not result.is_file():
        raise ValueError('Source file escapes extraction directory')
    return result


def bsp_selection(text):
    if not text.strip():
        return None
    parts = [v.strip() for v in text.split(',')]
    if any(not re.fullmatch(r'[0-9]+', v) for v in parts):
        raise ValueError('BSP indices must be comma-separated nonnegative integers')
    values = [int(v) for v in parts]
    if len(set(values)) != len(values) or any(v >= 64 for v in values):
        raise ValueError('Duplicate or out-of-range BSP index')
    return set(values)


def validate_scene(data, source_tag=None):
    if (data.get('format') != 'foundry.h3-scene' or type(data.get('version')) is not int
            or data['version'] != 1 or data.get('game') != 'halo3_mcc'
            or data.get('units') != 'ass_100_per_world_unit'
            or data.get('destination_tags_written') is not False):
        raise ValueError('Unsupported H3 scene manifest')
    source = inspection.relative_path(data['source_tag']).as_posix()
    if not source.endswith('.scenario') or (source_tag is not None and source != source_tag.replace('\\', '/')):
        raise ValueError('Scene source identity mismatch')
    if data.get('inventory') != 'scenario.h3inspect.json':
        raise ValueError('Unexpected scenario inventory path')
    entries = data.get('bsp_entries')
    if not isinstance(entries, list) or len(entries) > 64:
        raise ValueError('Invalid BSP table')
    seen = set()
    for row in entries:
        index = integer(row['index'])
        if index in seen or index >= 64:
            raise ValueError('Duplicate or out-of-range BSP identity')
        seen.add(index)
        if row.get('status') not in ('extracted', 'not_requested', 'error'):
            raise ValueError('Unknown BSP extraction status')
        if row.get('source_tag') is not None:
            if not inspection.relative_path(row['source_tag']).as_posix().endswith('.scenario_structure_bsp'):
                raise ValueError('Wrong BSP source class')
        if row['status'] == 'extracted':
            if row.get('geometry') != f'geometry/bsp_{index:04d}.json' or row.get('source_tag') is None:
                raise ValueError('Invalid extracted BSP record')
        if not isinstance(row.get('diagnostics'), list):
            raise ValueError('Missing BSP diagnostics')
    for shader in data.get('shader_paths', []):
        inspection.relative_path(shader)
    return data


def load_scene(path, source_tag=None, progress=None):
    path = Path(path)
    data = validate_scene(checked_json(path), source_tag)
    inventory = inspection.load(within(path.parent, data['inventory']), progress=progress)
    if inventory['source_tag'].replace('\\', '/') != data['source_tag'].replace('\\', '/'):
        raise ValueError('Inventory belongs to another scenario')
    for row in data['bsp_entries']:
        if row['status'] == 'extracted':
            within(path.parent, row['geometry'])
    return data, inventory


def result_messages(data):
    entries = data['bsp_entries']
    extracted = [row for row in entries if row['status'] == 'extracted']
    failed = [row for row in entries if row['status'] == 'error']
    yield (f'H3 BSP results: {len(extracted)} extracted, {len(failed)} failed, '
           f'{len(entries) - len(extracted) - len(failed)} not requested; '
           f'{len(data.get("shader_paths", []))} source shaders')
    for row in failed:
        for error in row['diagnostics']:
            yield f'H3 BSP {row["index"]} ({row.get("source_tag")}): {error}'
    if data.get('geometry_requested') and not extracted:
        yield 'H3 scenario has no extracted BSP geometry; only enabled hints and source inventory will be imported.'


def validate_bsp(data, source_tag, index):
    if (data.get('format') != 'foundry.h3-bsp' or type(data.get('version')) is not int
            or data['version'] != 1 or data.get('units') != 'ass_100_per_world_unit'
            or data.get('source_tag') != source_tag or type(data.get('bsp_index')) is not int
            or data['bsp_index'] != index):
        raise ValueError('BSP identity or format mismatch')
    materials, objects, instances = data['materials'], data['objects'], data['instances']
    if not all(isinstance(v, list) for v in (materials, objects, instances)):
        raise ValueError('Invalid BSP arrays')
    for slot, material in enumerate(materials):
        if type(material.get('slot')) is not int or material['slot'] != slot:
            raise ValueError('Material slot identity mismatch')
        if 'destination_shader' not in material or material['destination_shader'] is not None:
            raise ValueError('Source materials cannot assign Reach shaders')
        if material.get('source_shader') is not None:
            inspection.relative_path(material['source_shader'])
    for index, obj in enumerate(objects):
        if type(obj.get('id')) is not int or obj['id'] != index:
            raise ValueError('Definition identity mismatch')
        if obj.get('kind') == 'mesh':
            vertices = obj['vertices']
            for vertex in vertices:
                numbers(vertex['position'], 3)
                numbers(vertex['normal'], 3)
                numbers(vertex['color'], 3)
                if not isinstance(vertex['uvs'], list):
                    raise ValueError('Invalid UV channels')
                for uv in vertex['uvs']:
                    numbers(uv, 3)
                for node, weight in vertex['weights']:
                    integer(node, -1)
                    numbers([weight], 1)
                    if weight < 0:
                        raise ValueError('Negative source skin weight')
            for triangle in obj['triangles']:
                ids = triangle['vertices']
                if len(ids) != 3 or any(integer(v) >= len(vertices) for v in ids) or len(set(ids)) != 3:
                    raise ValueError('Invalid or degenerate source triangle')
                if integer(triangle['material'], -1) >= len(materials):
                    raise ValueError('Triangle references missing material')
        elif obj.get('kind') == 'sphere_marker':
            numbers([obj['radius']], 1)
            if obj['radius'] < 0:
                raise ValueError('Negative marker radius')
        elif obj.get('kind') != 'unsupported':
            raise ValueError('Unknown BSP definition kind')
    ids = set()
    for instance in instances:
        identity = integer(instance['id'])
        if identity in ids:
            raise ValueError('Duplicate placement identity')
        ids.add(identity)
        if integer(instance['object'], -1) >= len(objects):
            raise ValueError('Placement references missing definition')
        integer(instance['parent'], -1)
        for key in ('position', 'pivot_position'):
            numbers(instance[key], 3)
        for key in ('rotation', 'pivot_rotation'):
            if sum(v*v for v in numbers(instance[key], 4)) < 1e-12:
                raise ValueError('Zero placement quaternion')
        for key in ('scale', 'pivot_scale'):
            numbers([instance[key]], 1)
            if instance[key] == 0:
                raise ValueError('Singular placement scale')
        integer(instance['inheritance_flag'])
        for group in instance['bone_groups']:
            integer(group, -1)
    placement_order(instances)
    return data


def placement_order(instances):
    """Resolve parents without assuming decoder output is topologically sorted."""
    by_id = {row['id']: row for row in instances}
    result, visited = [], set()
    for start in by_id:
        path, active = [], set()
        identity = start
        while identity != -1 and identity not in visited:
            if identity not in by_id or identity in active:
                raise ValueError('Missing or cyclic placement parent')
            active.add(identity)
            path.append(identity)
            identity = by_id[identity]['parent']
        for identity in reversed(path):
            visited.add(identity)
            result.append(by_id[identity])
    return result


class FieldIndex:
    def __init__(self, data, roots=None):
        self.data = data
        self.children = defaultdict(list)
        self.names = defaultdict(list)
        for row in inspection.iter_records(data, roots=roots or {'ai user hint data', 'zones', 'scripting data'}):
            parent = row['address'].rpartition('/')[0]
            self.children[parent].append(row)
            self.names[row['name']].append(row)

    def one(self, parent, name, kind=None, required=True):
        rows = [r for r in self.children[parent] if r['name'] == name and (kind is None or r['kind'] == kind)]
        if len(rows) > 1 or (required and not rows):
            raise ValueError(f'Missing or ambiguous field: {parent}/{name}')
        return rows[0] if rows else None

    def elements(self, parent, name):
        block = self.one(parent, name, 'block', required=False)
        return [(i, f"{block['address']}[{i}]") for i in range(block['count'])] if block else []

    def value(self, parent, name, default=None):
        row = self.one(parent, name, 'value', required=False)
        return row['value'] if row else default

    def point(self, parent, name):
        row = self.one(parent, name, 'value')
        if row['type'].replace('_', ' ') != 'real point 3d':
            raise ValueError('Expected a source point, not a vector or direction')
        return numbers(row['value']['values'], 3)


def hint_plan(data):
    """Keep source point order and refuse unlocated object-relative hints."""
    index = FieldIndex(data)
    result = {'sectors': [], 'rails': [], 'firing_positions': [], 'script_points': [], 'diagnostics': []}
    def warn(address, error):
        result['diagnostics'].append({'address': address, 'reason': str(error), 'drawn': False})
    def point_frame(parent, name, frame_name):
        frame = index.value(parent, frame_name)
        if type(frame) is not int or frame != -1:
            raise ValueError(f'{frame_name}={frame}: object-relative coordinate not resolved')
        return index.point(parent, name)
    for hint_index, hint_parent in index.elements('', 'ai user hint data'):
        lines = dict(index.elements(hint_parent, 'line segment geometry'))
        for giant_index, giant_parent in index.elements(hint_parent, 'giant hints'):
            for sector_index, parent in index.elements(giant_parent, 'giant sector hints'):
                try:
                    point_rows = index.elements(parent, 'points')
                    points = [point_frame(p, 'point', 'reference frame') for _, p in point_rows]
                    if len(points) < 3:
                        raise ValueError('Sector has fewer than three points')
                    result['sectors'].append({'address': parent, 'name': f'giant_sector_{hint_index}_{giant_index}_{sector_index}',
                                              'points': points, 'closed': True,
                                              'bsp_indices': [index.value(p, 'structure bsp') for _, p in point_rows], 'source_indices': [hint_index, giant_index, sector_index]})
                except (KeyError, TypeError, ValueError) as error:
                    warn(parent, error)
            for rail_index, parent in index.elements(giant_parent, 'giant rail hints'):
                try:
                    geometry_index = index.value(parent, 'geometry index')
                    if type(geometry_index) is not int or geometry_index not in lines:
                        raise ValueError('Giant rail references an invalid line segment')
                    line = lines[geometry_index]
                    points = [point_frame(line, f'Point {i}', f'reference frame {i}') for i in range(2)]
                    result['rails'].append({'address': parent, 'name': f'giant_rail_{hint_index}_{giant_index}_{rail_index}',
                        'points': points, 'closed': False, 'geometry_index': geometry_index, 'geometry_address': line,
                        'flags': index.value(line, 'Flags'),
                        'bsp_indices': [index.value(line, f'structure bsp {i}') for i in range(2)],
                        'source_indices': [hint_index, giant_index, rail_index]})
                except (KeyError, TypeError, ValueError) as error:
                    warn(parent, error)
    for zone_index, zone in index.elements('', 'zones'):
        zone_name = index.value(zone, 'name', f'zone_{zone_index}')
        areas = dict(index.elements(zone, 'areas'))
        for point_index, parent in index.elements(zone, 'firing positions'):
            try:
                point = point_frame(parent, 'position (local)', 'reference frame')
                area = index.value(parent, 'area')
                area_name = index.value(areas[area], 'name', '') if type(area) is int and area in areas else ''
                result['firing_positions'].append({'address': parent, 'name': f'{zone_name}/{area_name}/fp_{point_index}',
                    'points': [point], 'zone_index': zone_index, 'area_index': area,
                    'zone_flags': index.value(zone, 'flags'), 'flags': index.value(parent, 'flags'),
                    'bsp_index': index.value(parent, 'bsp index'), 'source_facing': index.value(parent, 'normal')})
            except (KeyError, TypeError, ValueError) as error:
                warn(parent, error)
    for _, script_data in index.elements('', 'scripting data'):
        for set_index, point_set in index.elements(script_data, 'point sets'):
            set_name = index.value(point_set, 'name', f'point_set_{set_index}')
            for point_index, parent in index.elements(point_set, 'points'):
                try:
                    point = point_frame(parent, 'position', 'reference frame')
                    name = index.value(parent, 'name', f'point_{point_index}')
                    result['script_points'].append({'address': parent, 'name': f'{set_name}/{name}', 'points': [point],
                        'bsp_index': index.value(point_set, 'bsp index'), 'source_facing': index.value(parent, 'facing direction')})
                except (KeyError, TypeError, ValueError) as error:
                    warn(parent, error)
    return result

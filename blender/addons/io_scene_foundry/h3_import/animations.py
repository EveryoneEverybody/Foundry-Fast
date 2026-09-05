"""Validation and node matching for H3 animation intermediates."""
import json
import math
from pathlib import Path, PurePosixPath

FORMAT = 'foundry.h3-animation'
KINDS = {'JMM': 'none', 'JMA': 'xy', 'JMT': 'xyyaw', 'JMZ': 'xyzyaw', 'JMO': 'none'}
CONTROL_PREFIXES = ('CTRL_', 'FK_', 'IK_', 'PT_')


def canonical_node(name):
    return name[2:] if name.startswith('b_') else name


def safe_file(root, relative):
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative:
        raise ValueError('Invalid animation file reference')
    parts = relative.split('/')
    if any(p in ('', '.', '..') for p in parts) or PurePosixPath(relative).is_absolute():
        raise ValueError('Animation file reference must be relative')
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Animation file escapes extraction directory')
    return path


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _vector(value, count):
    return isinstance(value, list) and len(value) == count and all(_number(v) for v in value)


def validate_manifest(data):
    if not isinstance(data, dict) or data.get('format') != FORMAT or type(data.get('version')) is not int or data.get('version') not in (1, 2):
        raise ValueError('Unsupported H3 animation manifest')
    expected = {'game': 'halo3_mcc', 'units': 'halo_world', 'jma_units': 'halo_world_x100',
                'quaternion_order': 'wxyz', 'rest_space': 'parent_local'}
    for key, value in expected.items():
        if data.get(key) != value:
            raise ValueError(f'Unexpected animation {key}')
    for key in ('source_tag', 'source_graph'):
        safe_file('.', data.get(key))
    nodes = data.get('nodes')
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 255:
        raise ValueError('Invalid animation skeleton')
    names = set()
    for index, node in enumerate(nodes):
        name, parent, rest = node.get('name'), node.get('parent'), node.get('rest', {})
        if not isinstance(name, str) or not name or any(c in name for c in '\n\r') or name in names:
            raise ValueError('Missing or duplicate animation node')
        names.add(name)
        if type(parent) is not int or (index == 0 and parent != -1) or (index > 0 and not 0 <= parent < index):
            raise ValueError('Animation skeleton must have one root and parent-before-child order')
        if not _vector(rest.get('position'), 3) or not _vector(rest.get('rotation'), 4):
            raise ValueError('Invalid source rest transform')
        if abs(sum(v * v for v in rest['rotation']) - 1) > 0.01:
            raise ValueError('Source rest quaternion is not normalized')
        if not _number(rest.get('scale')) or rest['scale'] <= 0:
            raise ValueError('Invalid source rest scale')
    clips = data.get('animations')
    if not isinstance(clips, list):
        raise ValueError('Missing animation records')
    indices, clip_names = set(), set()
    for clip in clips:
        index, name, status = clip.get('index'), clip.get('name'), clip.get('status')
        if type(index) is not int or index < 0 or index in indices:
            raise ValueError('Duplicate or invalid animation index')
        indices.add(index)
        if not isinstance(name, str) or not name or name in clip_names:
            raise ValueError('Missing or duplicate animation name')
        clip_names.add(name)
        if status not in ('decoded', 'unsupported', 'not_selected', 'error'):
            raise ValueError('Unknown animation status')
        if status != 'decoded':
            continue
        d = clip.get('decoded', {})
        kind = d.get('kind')
        if kind not in KINDS or clip.get('animation_type') != ('overlay' if kind == 'JMO' else 'base') or clip.get('world_relative'):
            raise ValueError('Unsupported decoded animation type')
        movement = {'JMM': 'none', 'JMA': 'dx,dy', 'JMT': 'dx,dy,dyaw', 'JMZ': 'dx,dy,dz,dyaw', 'JMO': 'none'}
        if clip.get('frame_info_type') != movement[kind]:
            raise ValueError('Animation kind and movement metadata disagree')
        count = d.get('decoded_frame_count')
        if type(count) is not int or not 0 < count <= 32767 or clip.get('source_frame_count') != count:
            raise ValueError('Animation frame counts disagree')
        layout = 'reference_then_codec_frames' if kind == 'JMO' else 'codec_frames_then_held_terminal'
        if d.get('file_frame_count') != count + 1 or d.get('frame_layout') != layout:
            raise ValueError('Invalid animation frame layout')
        if kind == 'JMO':
            validate_overlay(clip, nodes, data['version'], clips)
        if d.get('fps') != 30 or clip.get('source_node_count') != len(nodes):
            raise ValueError('Unexpected animation rate or node count')
        for field in ('jma_file', 'motion_file'):
            rel = d.get(field)
            if rel is None and field == 'motion_file' and kind in ('JMM', 'JMO'):
                continue
            safe_file('.', rel)
            if Path(rel).suffix.lower() != '.' + kind.lower():
                raise ValueError('Animation extension differs from its kind')
    return data


def validate_overlay(clip, nodes, version, clips):
    d = clip['decoded']
    if version != 2 or clip.get('blend_screen') != -1 or clip.get('object_space_parent_count') != 0:
        raise ValueError('Only schema-2 time overlays without blend-screen or object-space data are supported')
    if d.get('motion_file') is not None or d.get('movement_samples') != []:
        raise ValueError('Time overlay must not contain movement data')
    overlay = d.get('overlay', {})
    if (overlay.get('composition') != 'static_reference_then_parent_local_delta'
            or overlay.get('preview') != 'composed_on_fixed_reference'
            or overlay.get('reference_frame') != 1 or overlay.get('first_sample_frame') != 2):
        raise ValueError('Unknown overlay composition or reference layout')
    base = overlay.get('base', {})
    index = base.get('animation_index')
    if (base.get('method') != 'graph_action_candidate_first_frame' or base.get('graph_index') != -1
            or base.get('frame') != 0 or type(index) is not int or index < 0 or index == clip['index']
            or not isinstance(base.get('state'), str) or not base['state']):
        raise ValueError('Overlay requires an identified local graph base')
    records = [row for row in clips if row.get('index') == index]
    if (len(records) != 1 or records[0].get('name') != base.get('animation_name')
            or records[0].get('animation_type') != 'base' or records[0].get('world_relative')
            or records[0].get('source_node_count') != len(nodes)):
        raise ValueError('Overlay base identity disagrees with source animation records')
    for label in ('base_pose', 'reference_pose'):
        pose = overlay.get(label)
        if not isinstance(pose, list) or len(pose) != len(nodes):
            raise ValueError('Missing per-node overlay ' + label)
        for t in pose:
            if (not isinstance(t, dict) or not _vector(t.get('position'), 3) or not _vector(t.get('rotation'), 4)
                    or abs(sum(v*v for v in t['rotation']) - 1) > 0.01
                    or not _number(t.get('scale')) or t['scale'] <= 0):
                raise ValueError('Invalid overlay reference transform')
    flags = overlay.get('node_flags', {})
    for component in ('rotation', 'translation', 'scale'):
        for prefix in ('static_', 'animated_'):
            bits = flags.get(prefix + component)
            if not isinstance(bits, list) or len(bits) != len(nodes) or any(type(bit) is not bool for bit in bits):
                raise ValueError('Invalid overlay component flags')
        if any(a and b for a, b in zip(flags['static_' + component], flags['animated_' + component])):
            raise ValueError('Overlapping static and animated overlay flags')


def load_manifest(path):
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('Animation manifest exceeds 64 MiB')
    with path.open(encoding='utf-8') as stream:
        return validate_manifest(json.load(stream))


def node_mapping(nodes, target_parents):
    """Match only exact names or the b_ convention, never control bones."""
    candidates = {}
    for name in target_parents:
        if not name.startswith(CONTROL_PREFIXES):
            candidates.setdefault(canonical_node(name), []).append(name)
    mapping = {}
    for node in nodes:
        matches = candidates.get(canonical_node(node['name']), [])
        if len(matches) != 1:
            raise ValueError(f'Expected one target for {node["name"]}; found {matches}')
        mapping[node['name']] = matches[0]
    if len(set(mapping.values())) != len(mapping):
        raise ValueError('Multiple source nodes map to the same target')
    pedestal = None
    for i, node in enumerate(nodes):
        target = mapping[node['name']]
        parent = target_parents[target]
        if i == 0:
            if parent is not None:
                if canonical_node(parent) != 'pedestal' or target_parents[parent] is not None:
                    raise ValueError('Source root may only be under a root pedestal')
                pedestal = parent
        elif parent != mapping[nodes[node['parent']]['name']]:
            raise ValueError(f'Hierarchy mismatch for {node["name"]}')
    if canonical_node(nodes[0]['name']) == 'pedestal':
        pedestal = mapping[nodes[0]['name']]
    return mapping, pedestal


def validate_jma_header(path, expected_frames, expected_nodes):
    # The bundled decoder emits only the parent-local 16392 layout.
    with Path(path).open(encoding='utf-8') as stream:
        header = [stream.readline().strip() for _ in range(7)]
    try:
        version, frames, fps, actors, nodes = (int(header[i]) for i in (0, 1, 2, 3, 5))
    except (ValueError, IndexError) as exc:
        raise ValueError('Malformed JMA header') from exc
    if (version, frames, fps, actors, nodes) != (16392, expected_frames, 30, 1, expected_nodes):
        raise ValueError('JMA header disagrees with the source manifest')

"""Name-based hookups for editable Reach material staging."""
import hashlib
import json
import re
from .materials import color_space, named, source_material_key

GROUP_NAME = 'foundry_reach.shader'
CATEGORIES = ('albedo', 'bump_mapping', 'alpha_test', 'specular_mask',
              'material_model', 'environment_mapping', 'self_illumination', 'blend_mode')


def normalized(name):
    return name.strip(' _').lower().replace(' ', '_')


def stage_name(source, label=''):
    key = source_material_key(source)
    stem = label or key.rsplit('/', 1)[-1].rsplit('.', 1)[0]
    stem = re.sub(r'[^a-z0-9_]+', '_', stem.lower()).strip('_')[:30] or 'material'
    digest = hashlib.sha256(key.encode()).hexdigest()[:10]
    return f'h3_{stem}_{digest}'


def image_usage(name):
    name = normalized(name)
    if 'bump' in name or 'normal' in name:
        return 'data', 'Detail Normal Map' if 'detail' in name else 'Normal Map (aka zbump)'
    if 'self_illum' in name:
        return 'color', 'Self-Illum Map'
    if name == 'change_color_map':
        return 'data', 'Change Color Map'
    if 'specular' in name or 'mask' in name or 'noise' in name:
        return 'data', 'Specular Map' if 'specular' in name else 'Blend Map (linear for terrains)'
    if 'detail' in name:
        return 'color', 'Detail Map'
    return 'color', 'Diffuse Map'


def staged_image_key(bitmap, parameter_name):
    role, usage = image_usage(parameter_name)
    return (bitmap['path'].replace('\\', '/').casefold(), bitmap['index'],
            color_space(bitmap, role), usage)


def staged_image_name(bitmap, parameter_name):
    key = staged_image_key(bitmap, parameter_name)
    stem = re.sub(r'[^a-z0-9_]+', '_', key[0].rsplit('/', 1)[-1].lower())[:30]
    digest = hashlib.sha256(json.dumps(key).encode()).hexdigest()[:10]
    return f'h3_{stem}_{digest}'


def parameter_bindings(parameter, sockets, aliases=()):
    """Return compatible socket names without inferring undocumented aliases."""
    name = normalized(parameter['name'])
    names = {name, *(normalized(alias) for alias in aliases if alias)}
    kind = parameter['type']
    result = []
    for socket in sockets:
        if not socket.get('visible', True):
            continue
        label = normalized(socket['name'])
        channel = None
        for candidate in names:
            if kind == 'bitmap':
                # Shared alpha sockets use labels such as base_map.a/specular_mask.a.
                for part in label.split('/'):
                    if part in {candidate, candidate + '.rgb'}:
                        channel = 'color'
                    elif part == candidate + '.a':
                        channel = 'alpha'
            elif kind in {'color', 'argb color'}:
                if label == candidate:
                    channel = 'color_value'
                elif kind == 'argb color' and label == candidate + '_alpha':
                    channel = 'alpha_value'
            elif label == candidate:
                channel = 'value'
        if channel is None:
            continue
        target_type = socket['type']
        compatible = ((channel in {'color', 'color_value'} and target_type in {'RGBA', 'VECTOR'}) or
                      (channel in {'alpha', 'alpha_value'} and target_type == 'VALUE') or
                      (channel == 'value' and ((kind == 'real' and target_type == 'VALUE') or
                       (kind == 'int' and target_type in {'INT', 'VALUE'}) or
                       (kind == 'bool' and target_type == 'BOOLEAN'))))
        if compatible:
            result.append((socket['name'], channel))
    return result


def validate_shader(record):
    if record.get('group') != 'rmsh' or not record.get('source', '').lower().endswith('.shader'):
        raise ValueError('Reach staging currently supports ordinary .shader materials only')
    if record.get('status') != 'resolved_snapshot':
        raise ValueError('A resolved H3 parameter snapshot is required for staging')
    source_material_key(record['source'])
    return named(record['categories'], 'category'), named(record['parameters'], 'name')

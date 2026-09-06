"""Validate material manifests and plan Blender previews."""
import json
import math
from pathlib import Path

FORMAT = 'foundry.h3-shaders'
DETAIL_MULTIPLIER = 4.59479
ILLUMINATION_MODES = {'simple', 'simple_with_alpha_mask', 'from_albedo', 'illum_detail'}
ALBEDO_MODES = {'default', 'constant_color', 'detail_blend', 'two_change_color', 'four_change_color'}


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Non-finite material value')
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, list):
        for item in value:
            _finite(item)


def _vector(value, count):
    if not isinstance(value, list) or len(value) != count or any(
        isinstance(x, bool) or not isinstance(x, (int, float)) for x in value
    ):
        raise ValueError(f'Expected {count} numeric components')


def named(rows, key):
    if not isinstance(rows, list):
        raise ValueError('Expected a material record list')
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get(key), str) or not row[key]:
            raise ValueError(f'Missing {key}')
        if row[key] in result:
            raise ValueError(f'Duplicate {key}: {row[key]}')
        result[row[key]] = row
    return result


def validate_manifest(data, source_tag):
    if not isinstance(data, dict) or data.get('format') != FORMAT or data.get('version') != 1:
        raise ValueError('Unsupported H3 shader manifest')
    if data.get('source_game') != 'halo3_mcc' or data.get('source_tag') != source_tag:
        raise ValueError('Shader manifest belongs to a different source asset')
    _finite(data)
    shaders, bitmaps = data.get('shaders'), data.get('bitmaps')
    if not isinstance(shaders, dict) or not isinstance(bitmaps, dict):
        raise ValueError('Missing shader or bitmap records')
    for path, shader in shaders.items():
        if not isinstance(shader, dict) or shader.get('source') != path:
            raise ValueError('Shader source identity mismatch')
        if 'source_description' in shader:
            validate_source_description(shader['source_description'], path)
        if shader.get('status') != 'resolved_snapshot':
            continue
        categories = named(shader.get('categories'), 'category')
        if any(not isinstance(c.get('option'), str) for c in categories.values()):
            raise ValueError('Invalid category option')
        for p in named(shader.get('parameters'), 'name').values():
            kind = p.get('type')
            if kind not in {'bitmap', 'real', 'int', 'bool', 'color', 'argb color'}:
                raise ValueError('Unrecognized material parameter type')
            if p.get('extern'):
                if not isinstance(p['extern'], str):
                    raise ValueError('Invalid runtime extern')
                continue
            if kind == 'bitmap':
                if 'bitmap' in p and p['bitmap'] not in bitmaps:
                    raise ValueError('Missing referenced bitmap record')
                _vector(p.get('transform'), 4)
                if not isinstance(p.get('sampler'), dict):
                    raise ValueError('Missing sampler state')
            elif kind in {'color', 'argb color'}:
                _vector(p.get('value'), 4)
            elif kind == 'bool':
                if not isinstance(p.get('value'), bool):
                    raise ValueError('Invalid boolean parameter')
            elif isinstance(p.get('value'), bool) or not isinstance(p.get('value'), (int, float)):
                raise ValueError('Invalid scalar parameter')
    for bitmap in bitmaps.values():
        if not isinstance(bitmap, dict) or not isinstance(bitmap.get('path'), str):
            raise ValueError('Invalid bitmap identity')
        if not isinstance(bitmap.get('index'), int) or bitmap['index'] < 0:
            raise ValueError('Invalid bitmap index')
        if bitmap.get('preview'):
            for size in ('width', 'height'):
                if type(bitmap.get(size)) is not int or bitmap[size] < 1:
                    raise ValueError('Invalid bitmap dimensions')
            if bitmap['width'] * bitmap['height'] > 67_108_864:
                raise ValueError('Oversized bitmap preview')
            if str(bitmap.get('type', '')).lower() != '2d texture' or bitmap.get('depth') != 1:
                raise ValueError('Non-2D bitmap marked as a 2D preview')
    return data


def load_manifest(path, source_tag):
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('Shader manifest exceeds 64 MiB')
    data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_object_pairs)
    return validate_manifest(data, source_tag)


def preview_path(directory, relative):
    if not isinstance(relative, str):
        raise ValueError('Bitmap preview path is not text')
    normalized = relative.replace('\\', '/')
    if ':' in normalized or any(p in {'', '.', '..'} for p in normalized.split('/')):
        raise ValueError('Unsafe bitmap preview path')
    root = Path(directory).resolve(strict=True)
    path = (root / normalized).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in {'.tif', '.tiff'}:
        raise ValueError('Bitmap preview is outside the extraction or is not TIFF')
    return path


def image_key(bitmap, role):
    # Color and data uses must not share a mutable image color-space setting.
    return bitmap['path'].replace('\\', '/'), bitmap['index'], role


def color_space(bitmap, role):
    if role != 'color' or str(bitmap.get('curve', '')).lower() == 'linear':
        return 'Non-Color'
    return 'sRGB'


def illumination_surface(categories, group):
    """Select an unlit preview only when no lighting or coverage pass is needed."""
    if (group != 'rmsh' or categories.get('self_illumination') not in ILLUMINATION_MODES
            or categories.get('material_model') != 'none'
            or categories.get('environment_mapping', 'none') not in {'none', 'off'}
            or categories.get('alpha_test', 'none') not in {'none', 'off'}):
        return 'principled'
    blend = categories.get('blend_mode', 'opaque')
    return {'opaque': 'emission', 'additive': 'additive'}.get(blend, 'principled')


def plan(shader):
    if shader.get('status') != 'resolved_snapshot':
        raise ValueError(shader.get('error', 'Shader metadata is unresolved'))
    categories = {k: v['option'] for k, v in named(shader['categories'], 'category').items()}
    diagnostics = list(shader.get('diagnostics', []))
    if 'source_description' in shader:
        description = validate_source_description(shader['source_description'], shader['source'])
        diagnostics.extend(f"Source {d['code']}: {d['message']}" for d in description['diagnostics'])
    albedo = categories.get('albedo', 'default')
    if albedo not in ALBEDO_MODES:
        diagnostics.append(f'Albedo {albedo}: base texture preview only')
    if shader.get('group') not in {'rmsh', 'rmtr'}:
        diagnostics.append(f"{shader.get('group')}: generic object preview, not the original shader family")
    diagnostics.append('Lighting, specular lobes, reflections and render passes use Blender approximations')
    if any(p.get('has_functions') for p in shader['parameters']):
        diagnostics.append('Material functions use their time-zero sample; source curves remain in metadata')
    return {'categories': categories, 'parameters': named(shader['parameters'], 'name'), 'family': shader.get('group'),
            'albedo': albedo, 'diagnostics': diagnostics,
            'illumination_surface': illumination_surface(categories, shader.get('group'))}


def bsp_material_issues(material, manifest):
    """Identify the failing stage without losing the exact BSP shader identity."""
    source = material.get('source_shader')
    if not source:
        if material.get('name', '').startswith(('+', '@')):
            # ASS auxiliary surface markers do not identify render shaders.
            return []
        return [('source_reference', 'BSP material has no source shader reference')]
    if manifest is None:
        return [('shader_description', 'Material preview manifest unavailable')]
    shader = manifest['shaders'].get(source)
    if shader is None:
        return [('shader_description', 'Referenced shader is absent from extracted descriptions')]
    if shader.get('status') != 'resolved_snapshot':
        return [('shader_description', shader.get('error', 'Shader description unresolved'))]
    issues = []
    if shader.get('group') not in {'rmsh', 'rmtr'}:
        issues.append(('shader_class', f"{shader.get('group')}: only a generic preview is available"))
    for parameter in shader.get('parameters', []):
        if parameter.get('type') != 'bitmap' or parameter.get('extern'):
            continue
        bitmap = manifest.get('bitmaps', {}).get(parameter.get('bitmap'))
        if not bitmap or not bitmap.get('preview'):
            issues.append(('bitmap_extraction', f"{parameter['name']}: {(bitmap or {}).get('preview_error') or (bitmap or {}).get('error') or 'No extracted 2D bitmap'}"))
    if shader.get('group') == 'rmtr':
        issues.append(('preview_coverage', 'Terrain layer albedo preview; Halo lighting, water/puddle reflections and detailed normal blending remain approximate'))
    return issues


def source_material_key(path):
    """Normalize a source identity without interpreting it as a Reach path."""
    if not isinstance(path, str) or not path or '\x00' in path:
        raise ValueError('Material source path must be nonempty text')
    normalized = path.replace('\\', '/')
    if ':' in normalized or any(p in {'', '.', '..'} for p in normalized.split('/')):
        raise ValueError('Unsafe material source path')
    if '.' not in normalized.rsplit('/', 1)[-1]:
        raise ValueError('Material source path needs its tag class')
    return normalized.casefold()


def validate_source_description(record, source):
    """Validate optional provenance separately from preview values."""
    if not isinstance(record, dict) or (record.get('format'), record.get('version'), record.get('game')) != (
        'foundry.h3-material', 1, 'halo3_mcc'
    ) or type(record.get('version')) is not int:
        raise ValueError('Unsupported H3 source material description')
    _finite(record)
    key = source_material_key(record.get('source_shader'))
    if key != source_material_key(source):
        raise ValueError('Material description belongs to a different source shader')
    if record.get('source_class') != key.rsplit('.', 1)[-1]:
        raise ValueError('Material source class does not match its path')
    status = record.get('description_status')
    if status not in {'resolved', 'partial', 'failed', 'unsupported'}:
        raise ValueError('Unknown material description status')
    if record.get('conversion_status') != 'source_only' or 'destination_shader' not in record or record['destination_shader'] is not None:
        raise ValueError('Source descriptions cannot assign destination shaders')
    diagnostics = record.get('diagnostics')
    if not isinstance(diagnostics, list) or any(not isinstance(d, dict) or
        not isinstance(d.get('code'), str) or not isinstance(d.get('message'), str) for d in diagnostics):
        raise ValueError('Invalid source material diagnostics')
    if status in {'resolved', 'partial'}:
        definition = source_material_key(record.get('definition'))
        if not definition.endswith('.render_method_definition'):
            raise ValueError('Invalid source render-method definition class')
        for name in ('categories', 'parameters', 'declarations', 'source_parameters'):
            if not isinstance(record.get(name), list):
                raise ValueError(f'Missing material {name} list')
        for parameter in named(record['parameters'], 'name').values():
            transform = parameter.get('texture_transform')
            if transform is not None:
                if not isinstance(transform, dict):
                    raise ValueError('Invalid source texture transform')
                _vector(transform.get('scale'), 2)
                _vector(transform.get('translation'), 2)
    return record

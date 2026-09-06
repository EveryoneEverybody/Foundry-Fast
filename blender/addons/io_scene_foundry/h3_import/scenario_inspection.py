"""Validate and query detached scenario inventories without loading host APIs."""
import json
import math
from pathlib import Path, PurePosixPath
import re

FORMAT = 'foundry.h3-scenario-inspection'
MAX_MANIFEST_BYTES = 256 * 1024 * 1024
MAX_RECORDS = 2_000_000
MAX_BLOB_BYTES = 512 * 1024 * 1024
BLOB_PATH = re.compile(r'blobs/[0-9]{6,}\.bin\Z')


class InspectionError(ValueError):
    pass


def relative_path(value):
    if not isinstance(value, str) or not value or '\x00' in value or ':' in value:
        raise InspectionError('Invalid source-relative path')
    value = value.replace('\\', '/')
    if value.startswith('/') or any(p in ('', '.', '..') for p in value.split('/')):
        raise InspectionError('Source-relative path escapes its root')
    return PurePosixPath(value)


def _int(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise InspectionError(f'Invalid {name}')
    return value


def _finite(value, depth=0):
    if depth > 96:
        raise InspectionError('Nested value exceeds depth limit')
    if isinstance(value, float) and not math.isfinite(value):
        raise InspectionError('Nonfinite values must retain bits and use a null value')
    if isinstance(value, dict):
        for child in value.values():
            _finite(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _finite(child, depth + 1)


def validate(data, directory=None):
    if (not isinstance(data, dict) or data.get('format') != FORMAT
            or type(data.get('version')) is not int or data['version'] != 1):
        raise InspectionError('Unsupported scenario inspection format')
    if data.get('source_group') != 'scnr' or relative_path(data.get('source_tag')).suffix != '.scenario':
        raise InspectionError('Expected a scenario source identity')
    if data.get('coordinate_encoding') != 'source_world_units_unmodified':
        raise InspectionError('Unsupported scenario coordinate encoding')
    if data.get('destination_tags_written') is not False:
        raise InspectionError('Expected a read-only source inventory')
    scope = data.get('scope')
    if not isinstance(scope, dict):
        raise InspectionError('Missing extraction scope')
    for name in ('bsp_dependencies_loaded', 'resource_payloads_decoded', 'scripts_executed', 'lossless_tag_roundtrip'):
        if scope.get(name) is not False:
            raise InspectionError(f'Unsupported inspection scope: {name}')
    records = data.get('records')
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise InspectionError('Invalid record table')
    addresses = {}
    blobs = set()
    total_bytes = 0
    root = Path(directory).resolve() if directory is not None else None
    for row in records:
        if not isinstance(row, dict):
            raise InspectionError('Invalid scenario field record')
        address = row.get('address')
        if not isinstance(address, str) or not address or address in addresses:
            raise InspectionError('Missing or duplicate field address')
        for name in ('name', 'raw_name', 'type'):
            if not isinstance(row.get(name), str):
                raise InspectionError(f'Missing field {name}: {address}')
        _int(row.get('ordinal'), 'field ordinal')
        kind = row.get('kind')
        if kind not in {'struct', 'block', 'array', 'resource_header_only', 'data', 'value'}:
            raise InspectionError(f'Unsupported record kind: {kind}')
        if kind in {'block', 'array'}:
            _int(row.get('count'), 'container count')
        if kind == 'value' and 'value' not in row:
            raise InspectionError(f'Missing source value: {address}')
        if kind == 'data':
            relative = row.get('file')
            if not isinstance(relative, str) or BLOB_PATH.fullmatch(relative) is None or relative in blobs:
                raise InspectionError('Invalid or duplicate blob path')
            blobs.add(relative)
            size = _int(row.get('bytes'), 'blob size')
            total_bytes += size
            if total_bytes > MAX_BLOB_BYTES:
                raise InspectionError('Scenario blobs exceed size limit')
            if root is not None:
                path = (root / relative).resolve()
                if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size != size:
                    raise InspectionError(f'Missing, escaped or truncated blob: {relative}')
        _finite(row)
        addresses[address] = row
    references = data.get('references')
    diagnostics = data.get('diagnostics')
    if not isinstance(references, list) or not isinstance(diagnostics, list):
        raise InspectionError('Missing source references or diagnostics')
    seen = set()
    for ref in references:
        if not isinstance(ref, dict):
            raise InspectionError('Invalid reference entry')
        address = ref.get('address')
        if not isinstance(address, str):
            raise InspectionError('Missing reference address')
        row = addresses.get(address)
        if address in seen or row is None or row.get('kind') != 'value' or row.get('value') != ref.get('reference'):
            raise InspectionError('Reference does not match its source field')
        seen.add(address)
        value = ref['reference']
        if not isinstance(value, dict) or not isinstance(value.get('path'), str):
            raise InspectionError('Invalid source reference value')
        if value['path']:
            relative_path(value['path'])
    _finite(diagnostics)
    return data


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise InspectionError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def load(path):
    path = Path(path)
    with path.open('rb') as handle:
        content = handle.read(MAX_MANIFEST_BYTES + 1)
    if len(content) > MAX_MANIFEST_BYTES:
        raise InspectionError('Scenario manifest exceeds size limit')
    data = json.loads(content, object_pairs_hook=_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(InspectionError(f'Invalid JSON value: {value}')))
    return validate(data, path.parent)


def named_fields(data, name):
    """Return exact named fields without merging equal names at different addresses."""
    return [row for row in data['records'] if row['name'] == name]


def subtree(data, address):
    """Keep indexed child fields in source order."""
    return [row for row in data['records'] if row['address'] == address
            or row['address'].startswith(address + '/') or row['address'].startswith(address + '[')]


def source_points(data, address):
    """Return point coordinates only. Vectors and unverified resource data are not positions."""
    points = []
    for row in subtree(data, address):
        if row['kind'] != 'value' or row['type'] != 'real point 3d':
            continue
        value = row['value']
        coords = value.get('values') if isinstance(value, dict) else None
        if (not isinstance(coords, list) or len(coords) != 3
                or any(type(n) not in (int, float) or not math.isfinite(n) for n in coords)):
            raise InspectionError(f'Point has no finite three-component value: {row["address"]}')
        points.append({'address': row['address'], 'position': tuple(coords)})
    return points


def dependency_requests(data, extension):
    """Inventory dependencies without opening, importing or assigning destination tags."""
    if not isinstance(extension, str) or re.fullmatch(r'[a-z0-9_]+', extension) is None:
        raise InspectionError('Invalid dependency extension')
    result = []
    for row in data['references']:
        ref = row['reference']
        if ref.get('extension') == extension and ref.get('path'):
            source = str(relative_path(ref['path'])) + '.' + extension
            result.append({'address': row['address'], 'source_tag': source, 'source_group': ref['group']})
    return result

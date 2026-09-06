"""Small JSON job records and owned pixel buffers, with no host API objects."""
import hashlib
import json
import math
import os
from pathlib import Path
import re

VERSION = 1
MAX_DIMENSION = 16384
JOB_ID = re.compile(r'^[0-9a-f]{32}$')


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, allow_nan=False), encoding='utf-8')
    os.replace(temporary, path)


def validate_recipe(recipe):
    if set(recipe) != {'width', 'height', 'format', 'cubemap', 'convert', 'gamma'}:
        raise ValueError('Unexpected bitmap recipe fields')
    for name in ('width', 'height'):
        if type(recipe[name]) is not int or not 0 < recipe[name] <= MAX_DIMENSION:
            raise ValueError(f'Invalid bitmap {name}')
    if type(recipe['format']) is not int or not 0 <= recipe['format'] <= 48:
        raise ValueError('Invalid bitmap format')
    if type(recipe['cubemap']) is not bool or type(recipe['convert']) is not bool:
        raise ValueError('Invalid bitmap conversion flags')
    if type(recipe['gamma']) not in (int, float) or not math.isfinite(recipe['gamma']) or not 0 < recipe['gamma'] <= 8:
        raise ValueError('Invalid bitmap gamma')
    if recipe['cubemap'] and (recipe['width'] != recipe['height'] or recipe['width'] % 2):
        raise ValueError('Cubemap faces must be square with even dimensions')
    return recipe


def reservation(recipe, payload_size):
    """Estimate detached buffers, including NumPy cubemap sampling intermediates."""
    validate_recipe(recipe)
    if type(payload_size) is not int or not 0 < payload_size <= 512 * 1024 * 1024:
        raise ValueError('Invalid bitmap payload size')
    pixels = recipe['width'] * recipe['height']
    return payload_size + pixels * (1400 if recipe['cubemap'] else 64)


def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def publish_missing(source, destination):
    """Publish a complete file without replacing an existing extraction."""
    import shutil
    import tempfile
    destination = Path(destination)
    if destination.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.foundry-bitmap-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as output, open(source, 'rb') as input_file:
            shutil.copyfileobj(input_file, output)
        try:
            # A hard link is an atomic create-if-absent on Windows NTFS and POSIX.
            os.link(name, destination)
        except FileExistsError:
            return False
        return True
    finally:
        Path(name).unlink(missing_ok=True)

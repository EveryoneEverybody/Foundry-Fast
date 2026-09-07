"""Consume an accepted immutable semantic plan without reopening loose source tags."""
import json
from pathlib import Path
from .model import stable_hash
from .paths import digest, relative, atomic_json


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def verify_files(files):
    for path, expected in files.items():
        if digest(path) != expected:
            raise ValueError('Accepted snapshot input changed: '+str(path))


def load(path, paths, scenario, zone):
    path = Path(path).resolve(strict=True)
    plan = read(path)
    if stable_hash({k:v for k,v in plan.items() if k != 'plan_sha256'}) != plan['plan_sha256']:
        raise ValueError('Accepted plan integrity mismatch')
    if plan.get('unsupported') or plan['source_semantic_resolution']['blocking_records']:
        raise ValueError('Accepted plan still has blocking source contracts')
    if (plan['source']['scenario'] != scenario or plan['selection']['source_zone_set'] != zone
            or plan['target']['namespace'] != paths.namespace
            or plan['target']['project_fingerprint'] != paths.fingerprint()):
        raise ValueError('Accepted plan selection/target differs from requested build')
    basis = plan['source_validation_basis']
    verify_files(basis['input_sha256'])
    source_run = Path(basis['source_run']).resolve(strict=True)
    manifest = source_run/'materials/authoring-shader-manifest.json'
    if str(manifest) not in basis['input_sha256']:
        raise ValueError('Effective shader recipe is not covered by accepted snapshot hashes')
    shaders = read(manifest)
    files = {str(path):digest(path), **basis['input_sha256']}
    for bsp in plan['bsps']:
        geometry = source_run/'source'/relative(bsp['geometry_source']['file'])
        if stable_hash(read(geometry)) != bsp['geometry_source']['canonical_sha256']:
            raise ValueError('Accepted decoded BSP changed: '+str(geometry))
        files[str(geometry)] = digest(geometry)
    for key, bitmap in plan['bitmaps'].items():
        name = bitmap.get('source_image') or bitmap['source_layout']['tiff']
        image = (source_run/'materials'/relative(name)).resolve(strict=True)
        if not image.is_relative_to(source_run/'materials'):
            raise ValueError('Snapshot pixel path escapes the source directory')
        files[str(image)] = digest(image)
    return plan, shaders, dict(source_run=str(source_run), source_directory=str(manifest.parent),
        shader_manifest=manifest.name, verified_files=files,
        source_validation='ACCEPTED_DECODED_SNAPSHOT', live_source_tags_read=False)


def save_receipt(run, snapshot):
    atomic_json(run/'accepted-snapshot-inputs.json', snapshot)

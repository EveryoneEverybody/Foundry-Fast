"""One import-scoped source/material cache shared by BSPs, selected sky and objects."""
import json
import os
from pathlib import Path
import subprocess
import time
from dataclasses import replace

from . import scenario_objects
from .core import load_payload
from .scenario_content import ContentIndex, tag_reference, plan
from .materials import load_manifest
from .material_builder import PreviewBuilder
from .import_output import HelperLogTail, HelperPending


def skies(inventory):
    index = ContentIndex(inventory, {'skies'})
    rows = []
    for i, address in index.elements('', 'skies'):
        metadata = index.metadata(address)
        try: source = tag_reference(index.value(address, 'sky'))
        except ValueError: source = ''
        rows.append(dict(index=i, address=address, source_tag=source, metadata=metadata))
    return rows


def selected_sky(rows, value):
    if not value or value == 'none': return None
    matches = [r for r in rows if value in (f"h3:{r['index']}", f"{r['index']}: {r['source_tag']}",
        r['source_tag'], r['source_tag'].replace('/', '\\'))]
    if len(matches) != 1 or not matches[0]['source_tag']:
        raise ValueError(f'Sky selection {value!r} does not identify exactly one source scenario sky')
    return matches[0]


def reference_dependencies(inventory, options):
    """Decode only model dependencies named by authored frames when objects are off."""
    from .scenario_frames import object_identifier
    index = ContentIndex(inventory, {'reference frames'})
    identifiers = set()
    for _, address in index.elements('', 'reference frames'):
        try: identifiers.add(object_identifier(index.metadata(index.struct(address, 'object id'))))
        except ValueError: pass
    source_options = replace(options, objects=True, sound=True, light_references=True,
                             ai=False, script_points=False, reference_debug=False)
    placements = plan(inventory, options=source_options)['placements']
    selected = {}
    by_name = {r['name_index']: r for r in placements if r['name_index'] >= 0}
    for row in placements:
        try:
            if object_identifier(row['metadata'].get('object id', {})) in identifiers:
                selected[row['address']] = row
        except ValueError: pass
    queue = list(selected.values())
    while queue:
        row = queue.pop()
        parent = by_name.get(row['parent_name_index'])
        if parent and parent['address'] not in selected:
            selected[parent['address']] = parent; queue.append(parent)
    requests = [dict(row, position=row.get('source_position')) for row in selected.values()]
    return placements, requests


def prepare(session, content):
    """Prune source requests before extraction, then deduplicate all shader work."""
    options = session.options
    session.sky_entries = skies(session.inventory)
    session.sky_entry = selected_sky(session.sky_entries, options.sky)
    requested = list(content['placements'])
    session.profile.counts['scenario_placement_source_requests'] = len({
        row['source_tag'] for row in content['placements'] if row.get('source_tag') and row.get('position') is not None})
    session.frame_placements = content['placements']
    if (options.ai or options.hints) and not options.objects:
        session.frame_placements, dependencies = reference_dependencies(session.inventory, options)
        requested.extend(dependencies)
        session.profile.counts['reference_model_requests'] = len({r['source_tag'] for r in dependencies if r['source_tag']})
    if session.sky_entry:
        requested.append(dict(source_tag=session.sky_entry['source_tag'], variant='', position=[0., 0., 0.]))
    session.profile.counts['source_asset_requests'] = len({
        row['source_tag'] for row in requested if row.get('source_tag') and row.get('position') is not None})
    assets = session.object_assets
    if assets is None and requested and session.tags_root and session.object_helper:
        started = time.perf_counter()
        assets = yield from scenario_objects.extract(dict(placements=requested), session.tags_root,
            session.directory, session.object_helper, shaders=False)
        session.profile.elapsed('unique source extraction elapsed', time.perf_counter() - started)
    assets = assets or {}
    helper_stats = getattr(assets, 'stats', None)
    if helper_stats:
        session.profile.counts['object_helper_processes'] = helper_stats['processes']
        session.profile.counts['object_helper_geometry_processes'] = helper_stats['geometry_processes']
        session.profile.counts['object_helper_material_processes'] = helper_stats['material_processes']
        session.profile.counts['object_helper_sources'] = helper_stats.get('unique_sources', len(assets))
        session.profile.elapsed('source asset helper subprocess wall sum', helper_stats['process_seconds'])
        print(f"H3 source asset helper profile: {helper_stats['processes']} processes, "
              f"{helper_stats['process_seconds']:.3f}s cumulative subprocess wall; "
              f"{helper_stats.get('unique_sources', len(assets))} unique sources", flush=True)
    session.object_assets = assets
    if not options.materials: return assets
    if session.material_manifest is None and session.tags_root and session.object_helper:
        shader_paths = set(session.scene.get('shader_paths', []) if options.geometry else [])
        bindings = len(shader_paths)
        for asset in assets.values():
            if asset.get('status') != 'extracted': continue
            try:
                paths = load_payload(asset['asset']).get('shader_paths', [])
                bindings += len(paths)
                shader_paths.update(paths)
            except (OSError, ValueError) as error:
                session.warnings.append(str(error))
        session.profile.counts['shader_cache_hits'] = bindings - len(shader_paths)
        if shader_paths:
            request = dict(format='foundry.h3-scene', version=1, game='halo3_mcc',
                source_tag=session.scene['source_tag'], shader_paths=sorted(shader_paths))
            request_path = session.directory / 'scenario-material-request.json'
            request_path.write_text(json.dumps(request), encoding='utf-8')
            helper = Path(session.object_helper).with_name('h3-shader-bridge.exe' if os.name == 'nt' else 'h3-shader-bridge')
            started = time.perf_counter()
            process = None
            try:
                log_path = session.directory / 'scenario-materials.log'
                with log_path.open('w', encoding='utf-8') as log:
                    process = subprocess.Popen([str(helper), '--tags-root', str(session.tags_root),
                        '--asset', str(request_path), '--output', str(session.directory)],
                        stdout=log, stderr=subprocess.STDOUT,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    tail = HelperLogTail(); tail.follow(log_path)
                    last_read = 0.
                    while process.poll() is None:
                        if time.monotonic() - last_read >= .1:
                            tail.poll(); last_read = time.monotonic()
                        yield HelperPending('Shared BSP, sky and object material extraction')
                    tail.poll(final=True)
                    if process.returncode: raise ValueError(f'Scenario shader helper failed ({process.returncode}); see {log_path}')
                # A scenario combines hundreds of independently bounded assets.
                session.material_manifest = load_manifest(session.directory / 'shader_manifest.json', session.scene['source_tag'], max_bytes=256 * 1024 * 1024)
            except (OSError, ValueError) as error:
                session.warnings.append(str(error))
            finally:
                if process and process.poll() is None: process.kill(); process.wait(timeout=3)
                session.profile.elapsed('shared shader and bitmap extraction', time.perf_counter() - started)
    if session.material_manifest:
        session.preview = PreviewBuilder(session.material_manifest, session.directory, session.remember, session.flip_normal_green)
        session.preview.reuse_materials = True
        session.shader_source = session.text('H3 scenario shader source', session.material_manifest)
        session.preview.source_text = session.shader_source.name
        session.root['h3_shader_manifest'] = session.shader_source.name
        session.profile.counts['unique_shaders'] = len(session.material_manifest['shaders'])
        session.profile.counts['unique_bitmaps'] = len(session.material_manifest['bitmaps'])
        if 'cache' in session.material_manifest:
            session.profile.counts['bitmap_cache_hits'] = session.material_manifest['cache']['bitmap_cache_hits']
    return assets

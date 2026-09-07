"""Reuse the H3 object helper and BuildSession for cached scenario references."""
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from .core import load_payload
from .scenario_inspection import relative_path
from .import_output import HelperLogTail, HelperPending
from .scenario_scene import checked_json


def load_semantic(path, source):
    data = checked_json(path, limit=32*1024*1024)
    if (data.get('format') != 'foundry.h3-semantic' or type(data.get('version')) is not int or data['version'] != 1
            or data.get('source_tag') != source or data.get('game') != 'halo3_mcc'
            or data.get('destination_tags_written') is not False or not isinstance(data.get('records'), list)):
        raise ValueError('Invalid semantic source description or identity')
    return data


def children(payload, variant):
    variant = variant or payload.get('default_variant', '')
    matches = [row for row in payload.get('variants', []) if row.get('name') == variant]
    if len(matches) != 1:
        return [], [f'Child attachment variant {variant!r} is unresolved'] if any(v.get('children') for v in payload.get('variants', [])) else []
    result, diagnostics = [], []
    for index, child in enumerate(matches[0].get('children', [])):
        source = child.get('source_tag')
        if not source:
            diagnostics.append(f'Child attachment {index}: source tag class unavailable; re-extract with the current helper')
            continue
        try: source = relative_path(source).as_posix()
        except ValueError as error:
            diagnostics.append(f'Child attachment {index}: {error}'); continue
        result.append(dict(child, source_tag=source, source_index=index, parent_variant=variant))
    return result, diagnostics


def requests(content):
    return sorted({row['source_tag'] for row in content['placements'] if row['source_tag'] and row['position'] is not None})


def extract(content, tags_root, directory, helper, shaders=True):
    """Each unique source runs once. Closing the generator stops its active helper."""
    assets = {}
    root = Path(tags_root).resolve(strict=True)
    directory = Path(directory).resolve()
    if directory.is_relative_to(root):
        raise ValueError('Object extraction output must be outside source tags')
    sources = set(requests(content))
    queue = deque(dict.fromkeys((row['source_tag'], row['variant']) for row in content['placements'] if row['source_tag'] in sources))
    payloads = {}
    visited = set()
    process = log = None
    try:
        while queue:
            source, variant = queue.popleft()
            if (source, variant) in visited: continue
            visited.add((source, variant))
            if len(visited) > 4096: raise ValueError('Source attachment dependency budget exceeded')
            if source in assets:
                if assets[source].get('status') == 'extracted':
                    attachments, _ = children(payloads[source], variant)
                    queue.extend((c['source_tag'], c.get('variant', '')) for c in attachments)
                continue
            prefix = f'Unique placed/child source {len(assets) + 1}: {source}'
            yield prefix
            output = directory / 'placed_sources' / hashlib.sha256(source.encode()).hexdigest()[:20]
            record = assets[source] = {'source_tag':source, 'status':'error', 'diagnostics':[]}
            try:
                path = (root / relative_path(source)).resolve(strict=True)
                if not path.is_relative_to(root) or not path.is_file():
                    raise ValueError('Placed source escapes the source tags directory')
                output.mkdir(parents=True, exist_ok=True)
                asset = output / 'asset.h3asset.json'
                semantic = output / 'source.h3semantic.json'
                stages = [('geometry', Path(helper), ['--tags-root', str(root), '--input', str(path), '--output', str(output)])]
                shader_helper = Path(helper).with_name('h3-shader-bridge.exe' if os.name == 'nt' else 'h3-shader-bridge')
                if shaders:
                    stages.append(('materials',shader_helper,['--tags-root',str(root),'--asset',str(asset),'--output',str(output)]))
                for phase, executable, arguments in stages:
                    if semantic.exists(): break
                    target = asset if phase == 'geometry' else output/'shader_manifest.json'
                    if target.exists():
                        continue
                    if not executable.is_file():
                        raise FileNotFoundError(f'Missing {phase} helper: {executable.name}')
                    log_path = output / f'{phase}.log'
                    log = log_path.open('w',encoding='utf-8')
                    tail = HelperLogTail();tail.follow(log_path)
                    process = subprocess.Popen([str(executable), *arguments], stdout=log, stderr=subprocess.STDOUT,
                        cwd=str(output),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    last_read = 0.
                    while process.poll() is None:
                        if time.monotonic()-last_read >= .1:
                            tail.poll();last_read=time.monotonic()
                        yield HelperPending(prefix + f' ({phase})')
                    code=process.returncode
                    process=None;log.close();log=None
                    details=tail.poll(final=True)
                    if code:
                        record['diagnostics'].append(f'{phase} helper failed ({code}): {details[-1600:]}')
                        print(f"H3 placed source unresolved: {source}: {record['diagnostics'][-1]}",flush=True)
                        if phase=='geometry':break
                if semantic.exists():
                    load_semantic(semantic, source)
                    record.update(status='semantic', semantic=str(semantic))
                elif asset.exists():
                    payload=load_payload(asset)
                    if payload['source_tag'] != source:
                        raise ValueError('Placed extraction source identity mismatch')
                    payloads[source] = payload
                    record.update(status='extracted',asset=str(asset))
                    attachments, diagnostics = children(payload, variant)
                    record['diagnostics'].extend(diagnostics)
                    queue.extend((c['source_tag'], c.get('variant', '')) for c in attachments)
            except (OSError,ValueError,KeyError,TypeError) as error:
                record['diagnostics'].append(str(error))
                print(f'H3 placed source unresolved: {source}: {error}',flush=True)
            finally:
                if process is not None and process.poll() is None:
                    process.kill();process.wait(timeout=3)
                process = None
                if log is not None:
                    log.close();log=None
        return assets
    finally:
        if process is not None and process.poll() is None:
            process.kill();process.wait(timeout=3)
        if log is not None:log.close()


def variant_regions(payload, variant):
    """Only select explicitly named deterministic permutations; never roll probabilities."""
    if not variant:
        variant=payload.get('default_variant','')
    if not variant:
        return None, ['No explicit model variant; all decoded permutations retained']
    matches=[v for v in payload.get('variants',[]) if v['name']==variant]
    if len(matches)!=1:
        return None,[f'Variant {variant!r} is unresolved; all decoded permutations retained']
    selected={}
    diagnostics=[]
    from .core import groups
    decoded = {}
    for key in groups(payload['render']):
        decoded.setdefault(key[0], set()).add(key[1])
    for region in matches[0]['regions']:
        permutations=region['permutations']
        if region.get('parent_variant',-1)!=-1 or len(permutations)!=1:
            diagnostics.append(f"Region {region['name']}: variant inheritance or probabilistic permutations retained without choosing")
            continue
        if permutations[0]['name'] not in decoded.get(region['name'], set()):
            diagnostics.append(f"Region {region['name']}: named permutation is absent from decoded geometry; region retained unfiltered")
            continue
        selected[region['name']]={permutations[0]['name']}
        if permutations[0].get('states'):
            diagnostics.append(f"Region {region['name']}: damage/state permutations retained; initial named permutation shown")
    return selected,diagnostics

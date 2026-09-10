"""Classify loose bitmap references against selected geometry and stock H3 bindings.

The source helper snapshot is immutable. A separate authoring snapshot may use
an exact, verified H3 cache binding; filename similarity is never evidence.
No cache pixels, tags, or compiled runtime payloads are copied by this module.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path

from .paths import digest, relative
from .authoring import issue


def canonical(value):
    return relative(value).as_posix().lower()


def bitmap_path(value):
    value = canonical(value)
    return value if value.endswith('.bitmap') else value + '.bitmap'


class TagInventory:
    """One complete walk, including hidden/ignored files; no basename remapping."""
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        self.files = {}
        self.basenames = defaultdict(list)
        def failed(error):
            raise error  # An incomplete tree search cannot establish absence.
        for directory, dirs, files in os.walk(self.root, onerror=failed, followlinks=False):
            for name in dirs:
                path = Path(directory) / name
                if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                    raise ValueError('Cannot claim a complete inventory across a redirected directory: ' + str(path))
            for name in files:
                path = Path(directory) / name
                identity = path.relative_to(self.root).as_posix().lower()
                if identity in self.files:
                    raise ValueError('Ambiguous case-insensitive source identity: ' + identity)
                self.files[identity] = path
                self.basenames[name.lower()].append(identity)
        names = sorted(self.files)
        self.summary = dict(source_kind='loose_h3ek', root=str(self.root), file_count=len(names),
            names_sha256=hashlib.sha256(('\n'.join(names)+'\n').encode()).hexdigest(),
            scope='Entire installed H3 tags tree, including hidden and ignored files')

    def search(self, source):
        source = canonical(source)
        return dict(exact_present=source in self.files,
                    exact_basename_matches=sorted(self.basenames.get(source.rsplit('/', 1)[-1], [])))

    def source_hash(self, source):
        path = self.files[canonical(source)].resolve(strict=True)
        if not path.is_relative_to(self.root):
            raise ValueError('Source dependency escapes installed tags root')
        return digest(path)


def shader_usage(bsps, skies):
    """Keep per-object triangle IDs and every placed use, excluding collision proxies."""
    result = defaultdict(list)
    for bsp in bsps:
        placements = defaultdict(list)
        for instance in bsp['instances']:
            if instance['object'] >= 0:
                placements[instance['object']].append(dict(id=instance['id'], name=instance['name']))
        collision_object = bsp['environment_semantics']['collision_object']
        for obj in bsp['objects']:
            if obj['id'] == collision_object or not placements[obj['id']] or obj.get('kind') == 'sphere_marker':
                continue
            by_material = defaultdict(list)
            for index, tri in enumerate(obj['triangles']):
                by_material[tri['material']].append(index)
            for slot, triangles in by_material.items():
                if not 0 <= slot < len(bsp['materials']):
                    raise ValueError('Invalid render material index in dependency usage')
                source = bsp['materials'][slot]['source_shader']
                if source:
                    result[canonical(source)].append(dict(kind='selected_bsp_render',
                        source_bsp=bsp['source_tag'], source_bsp_index=bsp['bsp_index'],
                        object_id=obj['id'], material_slot=slot, triangle_indices=triangles,
                        unique_triangles=len(triangles), placements=placements[obj['id']],
                        placed_triangles=len(triangles)*len(placements[obj['id']])))
        semantics = bsp['environment_semantics']
        collision = defaultdict(list)
        for surface in semantics['collision_surfaces']:
            if surface['material'] >= 0:
                collision[surface['material']].append(surface['source_surface'])
        for slot, surfaces in collision.items():
            source = semantics['collision_materials'][slot]
            if source:
                result[canonical(source)].append(dict(kind='selected_bsp_collision',
                    source_bsp=bsp['source_tag'], material_slot=slot, source_surfaces=surfaces))
        authoring = semantics.get('authoring', {})
        for instance in authoring.get('instances', []):
            flags = instance['flags']['value']
            if not flags & 8 or flags & 2:
                continue
            definition = authoring['definitions'][instance['instance definition']]
            slots = Counter(t['material'] for t in definition.get('collision_mesh', {}).get('triangles', []))
            for slot, count in slots.items():
                source = semantics['collision_materials'][slot] if slot >= 0 else None
                if source:
                    result[canonical(source)].append(dict(kind='selected_instance_collision',
                        source_bsp=bsp['source_tag'], instance_index=instance['source_index'],
                        material_slot=slot, triangles=count))
    for sky in skies:
        # The sky decoder supplies the selected render-model dependency list.
        # Keep this conservative until per-part sky usage is separately proven.
        for source in sky['shader_paths']:
            result[canonical(source)].append(dict(kind='selected_sky_dependency', source_sky=sky['source_tag']))
    return dict(result)


def verify_cache_files(records, scenario):
    """Evidence is local and reviewable; reject stale files and unrelated missions."""
    wanted = canonical(scenario).removesuffix('.scenario')
    verified = []
    for record in records:
        if canonical(record['scenario']).removesuffix('.scenario') != wanted:
            continue
        if record.get('source_kind') != 'retail_cache':
            raise ValueError('Cache binding evidence must declare source_kind=retail_cache; regenerate legacy evidence')
        path = Path(record['cache']).resolve(strict=True)
        if path.stat().st_size != record['bytes'] or digest(path) != record['sha256']:
            raise ValueError('Stock cache evidence no longer matches cache bytes: ' + str(path))
        if record.get('reader', {}).get('mode') != 'read-only' or 'Halo3' not in record['cache_type']:
            raise ValueError('Expected read-only H3 cache binding evidence')
        verified.append(record)
    return verified


def close_vector(left, right):
    return (isinstance(left, list) and isinstance(right, list) and len(left) == len(right)
            and all(isinstance(x, (int, float)) and isinstance(y, (int, float))
                    and math.isfinite(x) and math.isfinite(y)
                    and math.isclose(x, y, rel_tol=1e-6, abs_tol=1e-6) for x, y in zip(left, right)))


def matching_binding(shader, parameter, cache_shader):
    """Only a matching shader configuration can establish the missing sampler's binding."""
    if shader.get('status') != 'resolved_snapshot' or shader.get('group') != 'rmsh':
        raise ValueError('Cache binding adapter requires a resolved H3 shader recipe')
    if any(c.get('status') != 'resolved' for c in shader.get('source_description', {}).get('categories', [])):
        raise ValueError('Loose shader option walk is incomplete')
    loose = [(c['category'], c['source_index'], c['option']) for c in shader['categories']]
    cached = [(c['name'], c['index'], c['option']) for c in cache_shader['categories']]
    if not loose or loose != cached:
        raise ValueError('Cache and loose shader category selections differ')
    properties = cache_shader['properties']
    if len(properties) != 1:
        raise ValueError('Multiple cache shader property blocks are not supported')
    props = properties[0]
    samplers = props['samplers']
    if ([s['index'] for s in samplers] != list(range(len(samplers)))
            or len({s['usage'] for s in samplers}) != len(samplers)):
        raise ValueError('Ambiguous cache sampler table')
    args = props['arguments']
    if [a['index'] for a in args] != list(range(len(args))) or len(args) != len(props['constants']):
        raise ValueError('Ambiguous cache argument table')
    params = {p['name']: p for p in shader['parameters']}
    bitmap_params = {p['name']: p for p in shader['parameters'] if p['type'] == 'bitmap' and p.get('bitmap')}
    if set(bitmap_params) != {s['usage'] for s in samplers}:
        raise ValueError('Cache sampler usages differ from active loose bitmap parameters')
    selected = None
    for sampler in samplers:
        name = sampler['usage']
        if not sampler['valid'] or sampler['group'] != 'bitm' or not sampler['bitmap']:
            raise ValueError('Cache sampler does not bind a valid H3 bitmap')
        p = bitmap_params[name]
        index = sampler['tiling_index']
        if not 0 <= index < len(args) or args[index]['name'] != name:
            raise ValueError('Cache sampler UV argument identity is unverified')
        if not close_vector(p.get('transform'), props['constants'][index]):
            raise ValueError('Cache and loose sampler transforms differ')
        if name == parameter['name']:
            selected = sampler
        elif bitmap_path(p['bitmap'].rsplit('#', 1)[0]) != bitmap_path(sampler['bitmap']):
            raise ValueError('Another active cache sampler differs from the loose shader')
    for arg, value in zip(args, props['constants']):
        p = params.get(arg['name'])
        if p is None:
            raise ValueError('Cache constant has no decoded loose parameter')
        if p['type'] == 'bitmap':
            continue
        expected = p.get('value')
        if isinstance(expected, (int, float)):
            expected = [expected]*4
        if not close_vector(expected, value):
            raise ValueError('Cache and loose shader constants differ')
    if selected is None:
        raise ValueError('Missing parameter has no exact cache sampler')
    return selected


def audit(manifest, bsps, skies, selection, inventory, cache_records=(), *, usage=None):
    effective = deepcopy(manifest)
    usage = shader_usage(bsps, skies) if usage is None else usage
    verified = verify_cache_files(cache_records, selection['source_scenario'])
    report = dict(version=1, source_scenario=selection['source_scenario'],
        source_zone_set=selection['source_zone_set'], inventory=inventory.summary,
        shader_usage=usage, missing_references=[], runtime_binding_overrides=[],
        cache_evidence_status='MATCHING_SCENARIO_VERIFIED' if verified else 'NO_MATCHING_SCENARIO_EVIDENCE',
        unsupported=[])
    needed_bitmaps = set()
    for identity, shader in effective['shaders'].items():
        identity = canonical(identity)
        uses = usage.get(identity, [])
        render_used = any(u['kind'] in {'selected_bsp_render', 'selected_sky_dependency'} for u in uses)
        active_names = {p['name'] for p in shader.get('parameters', [])}
        for authored in shader.get('authored_parameters', []):
            if authored.get('bitmap') and authored['name'] not in active_names:
                source = bitmap_path(authored['bitmap'])
                found = inventory.search(source)
                if not found['exact_present']:
                    resolved = shader.get('status') == 'resolved_snapshot' and bool(shader.get('categories'))
                    description = shader.get('source_description', {})
                    resolved = resolved and all(c.get('status') == 'resolved' for c in description.get('categories', []))
                    row = dict(source_bitmap=source, source_shader=identity,
                        parameter=authored['name'], classification=('INACTIVE_SHADER_OPTION_REFERENCE' if resolved else
                                                                    'UNRESOLVED_SHADER_PARAMETER_USAGE'),
                        selected_categories=shader.get('categories', []), tree_search=found,
                        explanation='Absent from selected option parameters' if resolved else 'Shader option walk is incomplete')
                    report['missing_references'].append(row)
                    if not resolved and render_used:
                        report['unsupported'].append(issue(identity, 'authored bitmap parameter usage', [authored['name']],
                            'Incomplete shader decode cannot establish whether a missing authored reference is inactive',
                            dependency=row))
        for parameter in shader.get('parameters', []):
            key = parameter.get('bitmap')
            if not key:
                continue
            original = manifest['bitmaps'].get(key)
            if original is None:
                raise ValueError('Active shader refers to a bitmap absent from the helper manifest: ' + key)
            source = bitmap_path(original['path'])
            found = inventory.search(source)
            if not found['exact_present']:
                row = dict(source_bitmap=source, source_shader=identity, parameter=parameter['name'],
                    source_shader_sha256=inventory.source_hash(identity), tree_search=found,
                    usage=uses, classification='OUTSIDE_SELECTED_RENDER_USAGE' if not render_used else 'ACTIVE_REFERENCE_UNRESOLVED',
                    cache_checks=[])
                report['missing_references'].append(row)
                candidates = []
                if render_used:
                    for record in verified:
                        matching = [s for s in record['shaders'] if canonical(s['name']) == identity.rsplit('.', 1)[0]]
                        check = dict(source_kind=record['source_kind'], cache=record['cache'],
                            sha256=record['sha256'], reader=record['reader'])
                        row['cache_checks'].append(check)
                        try:
                            if len(matching) != 1:
                                raise ValueError('Exact shader is absent or ambiguous in this cache')
                            sampler = matching_binding(shader, parameter, matching[0])
                            replacement = bitmap_path(sampler['bitmap'])
                            if replacement == source:
                                raise ValueError('Cache still requires the absent loose bitmap; pixel recovery remains necessary')
                            if not inventory.search(replacement)['exact_present']:
                                raise ValueError('Verified cache bitmap is absent loose; pixel recovery remains necessary')
                            replacement_key = canonical(sampler['bitmap']).removesuffix('.bitmap')+'#0'
                            decoded = effective['bitmaps'].get(replacement_key)
                            if decoded is None or decoded.get('status') != 'preview' or decoded.get('image_count') != 1:
                                raise ValueError('Verified H3 bitmap still needs supported source-pixel extraction')
                            if original['index'] != 0:
                                raise ValueError('Nonzero source bitmap image index is not supported by this binding audit')
                            check.update(status='VERIFIED_RUNTIME_BINDING', shader_tag_id=matching[0]['id'],
                                sampler=sampler, template=matching[0]['properties'][0]['template'])
                            candidates.append((replacement_key, check))
                        except (ValueError, KeyError, IndexError, TypeError) as exc:
                            check.update(status='UNRESOLVED', reason=str(exc))
                    if candidates and len({k for k, _ in candidates}) == 1 and all(c['status'] == 'VERIFIED_RUNTIME_BINDING' for c in row['cache_checks']):
                        replacement_key = candidates[0][0]
                        override = dict(source_shader=identity, parameter=parameter['name'],
                            source_shader_kind='loose_h3ek', binding_source_kind='retail_cache',
                            authoring_bitmap_source_kind='loose_h3ek',
                            original_bitmap=source, original_bitmap_key=key, authoring_bitmap_key=replacement_key,
                            authoring_bitmap=bitmap_path(effective['bitmaps'][replacement_key]['path']),
                            original_parameter=deepcopy(parameter),
                            source_shader_sha256=row['source_shader_sha256'],
                            authoring_bitmap_sha256=inventory.source_hash(effective['bitmaps'][replacement_key]['path']+'.bitmap'),
                            cache_evidence=[c for _, c in candidates],
                            strategy='Verified stock H3 runtime sampler -> existing exact H3 bitmap -> source pixels -> Reach import')
                        parameter['bitmap'] = replacement_key
                        if (parameter['name'] == 'bump_detail_map' and shader.get('group') == 'rmsh'
                            and any(c['category'] == 'bump_mapping' and c['option'] == 'detail'
                                    for c in shader.get('categories', []))):
                            override['target_authoring_plan'] = dict(
                                target_tag_group='shader', target_node='foundry_reach.shader',
                                target_option=dict(bump_mapping='detail'), target_parameter='bump_detail_map',
                                parameter_binding=deepcopy(parameter), image_usage='Detail Normal Map',
                                uv_convention='H3 scale XY / translation ZW through Foundry Texture Tiling',
                                binding_evidence='Verified H3 retail sampler; pixels from exact loose H3 bitmap',
                                target_evidence='REACH_BUMP_DETAIL',
                                distinct_detail_bitmap_required=False,
                                alpha_policy='Preserve source alpha_test and blend_mode independently',
                                native_writes=False)
                        for description in shader.get('source_description', {}).get('parameters', []):
                            if description['name'] == parameter['name']:
                                description['resolved']['bitmap'] = override['authoring_bitmap']
                                description['runtime_binding_override'] = override
                        row['classification'] = 'STALE_LOOSE_REFERENCE_VERIFIED_RUNTIME_BINDING'
                        report['runtime_binding_overrides'].append(override)
                        key = replacement_key
                    else:
                        report['unsupported'].append(issue(identity, 'active bitmap dependency', [parameter['name']],
                            'Active source bitmap reference remains unresolved after full-tree and cache-evidence audit',
                            source_value=source, dependency=row))
                # Missing parameters outside the selected render usage do not
                # become runtime blockers. Their raw recipes and usage survive.
                if not render_used:
                    continue
            needed_bitmaps.add(key)
    effective['bitmaps'] = {k: v for k, v in effective['bitmaps'].items() if k in needed_bitmaps}
    report['classification_counts'] = dict(Counter(r['classification'] for r in report['missing_references']))
    report['original_bitmap_count'] = len(manifest['bitmaps'])
    report['authoring_bitmap_count'] = len(effective['bitmaps'])
    effective['environment_dependencies'] = report
    return effective, report


def cache_request(manifest, inventory, *, usage=None):
    """Only exact missing references are requested; the reader also inventories their names."""
    shaders, bitmaps = set(), set()
    for identity, shader in manifest['shaders'].items():
        if usage is not None and not any(u['kind'] in {'selected_bsp_render', 'selected_sky_dependency'}
                                         for u in usage.get(canonical(identity), [])):
            continue
        for p in shader.get('parameters', []):
            if p.get('bitmap'):
                bitmap = manifest['bitmaps'][p['bitmap']]
                source = bitmap_path(bitmap['path'])
                if not inventory.search(source)['exact_present']:
                    shaders.add(canonical(identity))
                    bitmaps.add(source)
    return dict(version=1, shaders=sorted(shaders), bitmaps=sorted(bitmaps))

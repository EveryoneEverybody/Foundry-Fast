"""Deterministic environment IR, with H3 provenance apart from Reach authoring."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math

from . import BUILDER_VERSION, FORMAT, SOURCE_SCENARIO
from . import fixtures
from .paths import digest, relative


def stable_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def finite(values, size):
    if (not isinstance(values, (list, tuple)) or len(values) != size
            or any(type(x) not in (int, float) or not math.isfinite(x) for x in values)):
        raise ValueError('Invalid/nonfinite geometry components')
    return values


def rotate(q, v):
    w, x, y, z = finite(q, 4)
    length = math.sqrt(sum(a*a for a in q))
    if length < 1e-10:
        raise ValueError('Zero source quaternion')
    w, x, y, z = (a/length for a in (w, x, y, z))
    a, b, c = finite(v, 3)
    return [(1-2*y*y-2*z*z)*a + (2*x*y-2*z*w)*b + (2*x*z+2*y*w)*c,
            (2*x*y+2*z*w)*a + (1-2*x*x-2*z*z)*b + (2*y*z-2*x*w)*c,
            (2*x*z-2*y*w)*a + (2*y*z+2*x*w)*b + (1-2*x*x-2*y*y)*c]


def transform(row, point, pivot=False):
    prefix = 'pivot_' if pivot else ''
    scale = row[prefix+'scale']
    finite([scale], 1)
    if scale <= 0:
        raise ValueError('Negative/zero BSP instance scale needs an explicit winding mapping')
    out = rotate(row[prefix+'rotation'], [p*scale for p in point])
    return [a+b for a, b in zip(out, finite(row[prefix+'position'], 3))]


def world_point(instance, point, instances):
    point = transform(instance, point, True)
    seen = set()
    while instance is not None:
        index = instance['id']
        if index in seen:
            raise ValueError('Cyclic source BSP transform')
        seen.add(index)
        if instance.get('inheritance_flag') != 0 or instance.get('bone_groups'):
            raise ValueError('Unsupported source BSP transform inheritance')
        point = transform(instance, point)
        parent = instance['parent']
        if parent != -1 and parent not in instances:
            raise ValueError('Missing BSP transform parent')
        instance = instances.get(parent)
    return point


def geometry_stats(meshes):
    points = [v['position'] for m in meshes for v in m['vertices']]
    return dict(vertices=len(points), triangles=sum(len(m['triangles']) for m in meshes),
                bounds_world=([min(p[i] for p in points)/100 for i in range(3)],
                              [max(p[i] for p in points)/100 for i in range(3)]) if points else None,
                material_triangles=dict(sorted(Counter(str(t['material']) for m in meshes
                                                        for t in m['triangles']).items())),
                geometry_sha256=stable_hash(meshes))


def validate_mesh(mesh, material_count):
    vertices, triangles = mesh['vertices'], mesh['triangles']
    if not vertices or not triangles:
        raise ValueError('Empty source mesh')
    for v in vertices:
        finite(v['position'], 3)
        finite(v['normal'], 3)
        for uv in v.get('uvs', []):
            finite(uv, len(uv))
            if len(uv) not in (2, 3):
                raise ValueError('Invalid source UV dimension')
    for t in triangles:
        if type(t['material']) is not int or not 0 <= t['material'] < material_count:
            raise ValueError('Unassigned/out-of-range source surface material')
        indices = t['vertices']
        if len(indices) != 3 or any(type(i) is not int or not 0 <= i < len(vertices) for i in indices):
            raise ValueError('Out-of-range source triangle')


def map_collision(bsp, *, sky_index=None):
    if sky_index is None:
        result = deepcopy(bsp)
    else:
        result = deepcopy({k:v for k,v in bsp.items() if k!='environment_semantics'})
        result['environment_semantics']={k:v for k,v in bsp['environment_semantics'].items() if k!='authoring'}
    semantics = result.get('environment_semantics', {})
    if semantics.get('version') != 1 or (sky_index is None and semantics.get('cluster_sky_indices') != [0]):
        raise ValueError('Proof requires verified source collision semantics and one sky-visible cluster')
    obj = result['objects'][semantics['collision_object']]
    sky_slot = len(result['materials'])
    result['materials'].append(dict(slot=sky_slot, name='+sky'+str(sky_index or 0), source_shader=None, special='sky'))
    cursor = 0
    for s in semantics['collision_surfaces']:
        count = s['triangle_count']
        if s['flags'] & ~(1 if sky_index is not None else 0) or s['triangle_start'] != cursor or count < 1:
            raise ValueError('Unsupported collision flags or incomplete source surface coverage')
        material = s['material']
        if material == -1:
            slot, kind = sky_slot, 'sky'
        elif 0 <= material < len(semantics['collision_materials']):
            source = semantics['collision_materials'][material]
            seam = (bsp.get('environment_semantics',{}).get('authoring',{}).get('collision_materials',[])[material]
                    if sky_index is not None and bsp['environment_semantics'].get('authoring') else {})
            if not source and seam.get('seam mapping index',-1)>=0:
                slot,kind=len(result['materials']),'seam'
                result['materials'].append(dict(slot=slot,name='+seam',source_shader=None,special='seam',
                    source_seam_mapping=seam['seam mapping index']))
                for t in obj['triangles'][cursor:cursor+count]:
                    t.update(material=slot,source_surface=s['source_surface'],source_collision_material=material,surface_type=kind)
                cursor+=count
                continue
            matches = [i for i, m in enumerate(result['materials']) if source and m.get('source_shader') == source]
            if source and (not matches or (sky_index is not None and len(matches)>1)):
                matches = [len(result['materials'])]
                result['materials'].append(dict(source_shader=source, name=source.rsplit('/',1)[-1],source_collision_material=material))
            if len(matches) != 1:
                raise ValueError('Ambiguous collision material source')
            slot, kind = matches[0], 'solid'
        else:
            raise ValueError('Unknown source collision material/sky encoding')
        for t in obj['triangles'][cursor:cursor+count]:
            t.update(material=slot, source_surface=s['source_surface'], source_collision_material=material, surface_type=kind)
            if s['flags']:
                t['two_sided'] = bool(s['flags'] & 1)
        cursor += count
    if cursor != len(obj['triangles']):
        raise ValueError('Incomplete collision surface coverage')
    return result


def bsp_meshes(bsp):
    if (bsp.get('format') != 'foundry.h3-bsp' or bsp.get('version') != 1
            or bsp.get('units') != 'ass_100_per_world_unit'):
        raise ValueError('Unsupported decoded BSP format/units')
    instances = {r['id']: r for r in bsp['instances']}
    if len(instances) != len(bsp['instances']):
        raise ValueError('Duplicate source BSP instance identity')
    result, omitted = [], []
    for row in bsp['instances']:
        if row['object'] == -1:
            continue
        if not 0 <= row['object'] < len(bsp['objects']):
            raise ValueError('Invalid BSP object reference')
        record = bsp['objects'][row['object']]
        if record['kind'] == 'sphere_marker':
            omitted.append(dict(source_instance=row['id'], name=row['name'], reason='Authored marker has no world surface'))
            continue
        if record['kind'] != 'mesh' or record.get('xref_path'):
            raise ValueError('Unresolved BSP mesh/xref cannot produce an accepted environment')
        if row['name'].startswith('+'):
            raise ValueError('Portal/weather/seam semantics require a separate proven mapping')
        mesh = deepcopy(record)
        validate_mesh(mesh, len(bsp['materials']))
        collision = row['name'] == '@CollideOnly'
        if row['name'].startswith('@') and not collision:
            raise ValueError('Unknown source collision category: ' + row['name'])
        for v in mesh['vertices']:
            if v.get('weights'):
                raise ValueError('Skinned source BSP cannot be flattened')
            v['position'] = world_point(row, v['position'], instances)
            normal = rotate(row['pivot_rotation'], v['normal'])
            current, seen = row, set()
            while current is not None:
                if current['id'] in seen:
                    raise ValueError('Cyclic BSP normal transform')
                seen.add(current['id'])
                normal = rotate(current['rotation'], normal)
                current = instances.get(current['parent'])
            v['normal'] = normal
        mesh.update(name=row['name'], source_instance=row['id'], source_transform=deepcopy(row),
                    role='collision' if collision else 'render',
                    mesh_type='_connected_geometry_mesh_type_structure',
                    face_mode='collision_only' if collision else 'render_only')
        result.append(mesh)
    if not any(m['role'] == 'collision' for m in result) or not any(m['role'] == 'render' for m in result):
        raise ValueError('Proof requires separately decoded H3 render and collision surfaces')
    return result, omitted


def spawn_above_collision(meshes):
    """Choose the highest upward source triangle under the XY bounds center."""
    collision = [m for m in meshes if m['role'] == 'collision']
    bounds = geometry_stats(collision)['bounds_world']
    x, y = [(bounds[0][i]+bounds[1][i])*50 for i in range(2)]
    hits = []
    for m in collision:
        for index, t in enumerate(m['triangles']):
            a, b, c = [m['vertices'][i]['position'] for i in t['vertices']]
            det = (b[0]-a[0])*(c[1]-a[1]) - (c[0]-a[0])*(b[1]-a[1])
            if det <= 1e-8:
                continue
            u = ((x-a[0])*(c[1]-a[1])-(c[0]-a[0])*(y-a[1]))/det
            v = ((b[0]-a[0])*(y-a[1])-(x-a[0])*(b[1]-a[1]))/det
            if min(u, v, 1-u-v) >= -1e-8:
                z = a[2]+u*(b[2]-a[2])+v*(c[2]-a[2])
                hits.append((z, m['source_instance'], index))
    if not hits:
        raise ValueError('No upward H3 collision triangle under the proposed spawn')
    z, instance, triangle = max(hits)
    return dict(position_world=[x/100, y/100, z/100+0.2], facing_degrees=0.0,
                classification='TARGET_DEFAULT', strategy='Compiler scaffolding above decoded H3 collision',
                supporting_source_instance=instance, supporting_source_triangle=triangle,
                surface_world_z=z/100, clearance_world=0.2)


def bitmap_strategy(bitmap):
    if (bitmap.get('image_count') != 1 or str(bitmap.get('type')).lower() != '2d texture'
            or bitmap.get('depth') != 1 or bitmap.get('index') != 0):
        raise ValueError('Only a single indexed 2D bitmap is supported in the box proof')
    if not 0 < bitmap.get('width', 0)*bitmap.get('height', 0) <= 67_108_864:
        raise ValueError('Invalid bitmap dimensions')
    if bitmap.get('preview'):
        return dict(source_image=relative(bitmap['preview']).as_posix(), strategy='H3 decoder TIFF -> Reach TIFF/bitmap')
    if bitmap.get('dds') and bitmap.get('format', '').lower() in {'dxt1', 'dxt3', 'dxt5', 'dxn', 'a8r8g8b8', 'x8r8g8b8'}:
        return dict(source_image=relative(bitmap['dds']).as_posix(),
                    strategy='H3 decoder single 2D DDS -> Blender pixels -> Reach TIFF/bitmap')
    raise ValueError('Source pixels unavailable: ' + str(bitmap.get('preview_error', bitmap.get('error'))))


def sky_lighting(root):
    if root.get('group') != 'render_model':
        raise ValueError('Expected source sky render model metadata')
    samples = []
    for element in fixtures.block(root, 'sky lights'):
        direction = [float(x) for x in fixtures.field(element, 'direction').split(',')]
        color = [float(x) for x in fixtures.field(element, 'intensity').split(',')]
        angle = float(fixtures.field(element, 'solid angle'))
        finite(direction, 3); finite(color, 3); finite([angle], 1)
        if abs(sum(x*x for x in direction)-1) > .001 or min(color) < 0 or not 0 < angle < 4*math.pi:
            raise ValueError('Invalid source sky lighting sample')
        samples.append(dict(direction=direction, intensity=color, solid_angle=angle))
    if len(samples) < 2 or len(samples) > 1024:
        raise ValueError('Source sky lighting sample contract changed')
    if max(c for s in samples[:-1] for c in s['intensity']) > 1:
        raise ValueError('Diffuse sky radiance exceeds the proven Blender color range')
    last = samples[-1]
    if last['solid_angle'] >= .001 or max(last['intensity']) < 1:
        raise ValueError('Source sky no longer ends in the proven narrow sun sample')
    # Preserve diffuse radiance/solid angle. Express the final narrow source
    # sample as Reach's analytic sun: irradiance = radiance * solid angle.
    # This is an explicit lighting approximation, not baked-lightmap migration.
    return dict(source_samples=samples, classification='GENERATED',
                strategy='Diffuse samples direct; narrow final sample becomes Reach analytic sun using radiance times solid angle',
                sun_irradiance=[c*last['solid_angle'] for c in last['intensity']],
                sun_size_degrees=math.degrees(2*math.acos(1-last['solid_angle']/(2*math.pi))),
                defaults=dict(sun_bounce_scale=1.0, skylight_bounce_scale=1.0))


def construct(paths, scene, bsp, sky, shaders, scenario_xml, lighting_xml, sky_xml, sky_render_xml, lighting_quality='direct_only',
              *, selection=None, designs=None, seams_xml=None, light_xmls=None):
    if selection is not None and selection['classification'] != 'TARGET_DEFAULT':
        return construct_selected(paths, scene, bsp, sky, shaders, scenario_xml, lighting_xml, sky_xml, sky_render_xml,
                                  selection, designs or {}, seams_xml, lighting_quality, light_xmls or {})
    if lighting_quality not in {'none', 'direct_only', 'draft'}:
        raise ValueError('Unsupported proof lighting quality')
    if (scene.get('source_tag') != SOURCE_SCENARIO or scene.get('game') != 'halo3_mcc'
            or len(scene.get('bsp_entries', [])) != 1 or scene['bsp_entries'][0]['status'] != 'extracted'):
        raise ValueError('This compiler milestone accepts only H3 levels/test/box with one decoded BSP')
    scenario = fixtures.scenario_semantics(scenario_xml)
    if scenario['identity']+'.scenario' != SOURCE_SCENARIO or scenario['type'] != 'solo':
        raise ValueError('Unexpected source scenario semantics')
    if len(scenario['bsps']) != 1 or len(scenario['skies']) != 1:
        raise ValueError('Box proof requires exactly one source BSP and sky')
    bsp_ref = fixtures.block(scenario_xml, 'structure bsps')[0]
    source_bsp = fixtures.reference(bsp_ref, 'structure bsp', 'scenario_structure_bsp')
    source_lighting = fixtures.reference(bsp_ref, 'structure lighting_info', 'scenario_structure_lighting_info')
    design = fixtures.reference(bsp_ref, 'structure design', 'structure_design')
    sky_ref = fixtures.block(scenario_xml, 'skies')[0]
    source_sky = fixtures.reference(sky_ref, 'sky', 'scenery')
    if bsp['source_tag'] != source_bsp or sky.get('source_tag') != source_sky:
        raise ValueError('Decoded geometry differs from the live H3 scenario relationships')
    if design:
        raise ValueError('Authored structure design found; mapping is catalogued, but this empty-design proof cannot omit it')
    if (sky.get('format') != 'foundry.h3-object' or sky.get('units') != 'jms_x100'
            or sky.get('game') != 'halo3_mcc' or sky.get('version') != 1):
        raise ValueError('Unsupported H3 sky source representation')
    # This fixture has one identity bind node. Reject a new skeleton contract.
    nodes = sky['render']['nodes']
    if (len(nodes) != 1 or nodes[0]['parent'] != -1 or any(nodes[0]['position'])
            or any(abs(x) > 1e-6 for x in nodes[0]['rotation'][1:])):
        raise ValueError('Nonidentity sky skeleton requires an explicit model transform adapter')
    if any(any(weight[0] != 0 for weight in v.get('weights', [])) for v in sky['render']['vertices']):
        raise ValueError('Sky is not rigidly bound to its single identity node')
    sky_mesh = deepcopy(sky['render'])
    validate_mesh(sky_mesh, len(sky_mesh['materials']))
    bsp = map_collision(bsp)
    meshes, omitted = bsp_meshes(bsp)
    if scenario['player_starts']:
        # Supported source starts are parsed explicitly, with no Reach XML value copying.
        start = scenario['player_starts'][0]
        point = [float(x) for x in start['position'].split(',')]
        finite(point, 3)
        spawn = dict(position_world=point, facing_degrees=float(start.get('facing', 0)),
                     classification='GENERATED', strategy='H3 player starting location')
    else:
        spawn = spawn_above_collision(meshes)
    lighting = fixtures.lighting_semantics(lighting_xml)
    if lighting['light_definitions'] or lighting['light_instances']:
        raise ValueError('Nonempty authored light definitions are outside the proven box mapping')
    if any(float(m['emissive power']) != 0 for m in lighting['materials']):
        raise ValueError('Nonzero H3 material emission requires a proven source surface index relationship')
    sources = {SOURCE_SCENARIO, source_bsp, source_lighting, source_sky, *sky['dependencies'].values()}
    material_plan = []
    for source, shader in sorted(shaders['shaders'].items()):
        if shader.get('status') != 'resolved_snapshot' or shader.get('group') != 'rmsh':
            raise ValueError('Unresolved source shader: ' + source)
        if any(p.get('has_functions') or p.get('extern') for p in shader['parameters']):
            raise ValueError('Animated/runtime material inputs are outside this proof')
        sources.add(source)
        stem = source.rsplit('/', 1)[1].rsplit('.', 1)[0]
        target = paths.namespace+'/shaders/'+stem+'_'+stable_hash(source)[:8]+'.shader'
        material_plan.append(dict(source_shader=source, source_parameters=shader['parameters'],
                                  source_categories=shader['categories'], destination=target,
                                  strategy='ReachStager -> Foundry ShaderTag.write_tag -> Reach shader templates',
                                  classification='GENERATED'))
    bitmaps = {}
    for key, bitmap in sorted(shaders['bitmaps'].items()):
        sources.add(relative(bitmap['path']).as_posix()+'.bitmap')
        bitmaps[key] = dict(bitmap_strategy(bitmap), source_bitmap=bitmap['path'], index=bitmap['index'])
    # Source option/default dependencies are hashed when explicit descriptions retain them.
    sources.add('shaders/shader.render_method_definition')
    source_hashes = {p: digest(paths.source(p)) for p in sorted(sources) if p}
    sky_materials = []
    for mat in sky_mesh['materials']:
        matches = [p for p in sky['shader_paths'] if p.rsplit('/', 1)[1].rsplit('.', 1)[0] == mat['name']]
        if len(matches) != 1:
            raise ValueError('Ambiguous source sky material')
        sky_materials.append(matches[0])
    mapping_file = __import__('pathlib').Path(__file__).with_name('mappings.json')
    catalog = json.loads(mapping_file.read_text(encoding='utf-8'))
    result = dict(format=FORMAT, version=1, builder_version=BUILDER_VERSION,
        source=dict(game='halo3_mcc', scenario=SOURCE_SCENARIO, hashes=source_hashes,
                    tags_root_fingerprint=hashlib.sha256(str(paths.h3_tags).casefold().encode()).hexdigest()),
        target=dict(game='haloreach_mcc', namespace=paths.namespace, scenario=paths.scenario+'.scenario',
                    project_fingerprint=paths.fingerprint(), units='ass_100_per_world_unit',
                    scene_scale='max', forward_direction='x'),
        bsp=dict(source_tag=source_bsp, materials=bsp['materials'], meshes=meshes, omitted=omitted,
                 collision_semantics=bsp['environment_semantics'],
                 source_render=geometry_stats([m for m in meshes if m['role']=='render']),
                 source_collision=geometry_stats([m for m in meshes if m['role']=='collision']),
                 destination=paths.namespace+'/proof_box_bsp.scenario_structure_bsp', structure_design=None),
        sky=dict(source_scenery=source_sky, source_model=sky['dependencies']['model'],
                 source_render_model=sky['dependencies']['render_model'], source_object_fields=fixtures.fields(sky_xml),
                 transform=dict(position=[0,0,0], rotation=[1,0,0,0], scale=1),
                 target_defaults=dict(imposter_policy='never', imposter_model='Unused Tool-authored placeholder'),
                 mesh=sky_mesh, materials=sky_materials, source_geometry=geometry_stats([sky_mesh]),
                 destination=paths.namespace+'/sky/proof_box_sky/proof_box_sky.scenery'),
        materials=material_plan, bitmaps=bitmaps,
        lighting=dict(source_tag=source_lighting, source_semantics=lighting,
                      strategy='Source material emission is zero; source sky samples rebuilt through normal Foundry sky export',
                      baked_source='OMITTED', quality=lighting_quality,
                      sky=sky_lighting(sky_render_xml)),
        scenario=dict(source_semantics=scenario, spawn=spawn, type='solo', sky_index=0,
                      active_bsp_mask=1, zone_set='proof_box', structure_designs=[],
                      defaults=dict(custom_gravity_scale=1.0, sky_cloud_scale=0.0, sky_cloud_speed=0.0,
                                    sky_cloud_direction=0.0, size_class='1Meg_512x512')),
        mappings_used=[r['id'] for r in catalog['rules']], mapping_catalog_sha256=digest(mapping_file),
        excluded=['AI','HSC','audio','cinematics','effects','H3 runtime resource payloads','H3 baked lightmap'],
        unknowns=['Runtime spawn, collision, visuals and sky require Nate in reach_tag_test.exe.',
                  'Sky analytic sun uses radiance times solid angle; exact H3/Reach lighting parity is unverified.',
                  'Matching shader option names does not establish rendering parity.'])
    result['plan_sha256'] = stable_hash(result)
    return result


def used_shaders(bsps, skies):
    """Canonical source identity shared by all triangles, definitions, and BSPs."""
    sources = set()
    for bsp in bsps:
        used_objects={row['object'] for row in bsp['instances'] if row['object']>=0}
        for obj in (bsp['objects'][i] for i in sorted(used_objects)):
            for t in obj.get('triangles', []):
                if 0 <= t['material'] < len(bsp['materials']):
                    source = bsp['materials'][t['material']].get('source_shader')
                    if source: sources.add(relative(source).as_posix())
        semantics=bsp['environment_semantics']
        used_collision={s['material'] for s in semantics['collision_surfaces'] if s['material']>=0}
        a=semantics.get('authoring',{})
        for row in a.get('instances',[]):
            flags=row['flags']['value']
            if flags & 8 and not flags & 2:
                definition=a['definitions'][row['instance definition']]
                used_collision.update(t['material'] for t in definition.get('collision_mesh',{}).get('triangles',[]) if t['material']>=0)
        sources.update(semantics['collision_materials'][i] for i in used_collision if semantics['collision_materials'][i])
    for sky in skies:
        sources.update(relative(s).as_posix() for s in sky['shader_paths'])
    return sorted(sources)


def plan_bsps(plan):
    return plan['bsps'] if 'bsps' in plan else [plan['bsp']]


def plan_skies(plan):
    return plan['skies'] if 'skies' in plan else [plan['sky']]


def construct_selected(paths, scene, bsps, skies, shaders, scenario_xml, lighting_xmls, sky_xmls, sky_render_xmls,
                       selection, designs, seams_xml, lighting_quality, light_xmls):
    from . import authoring
    if scene['source_tag'] != selection['source_scenario'] or scene['game'] != 'halo3_mcc':
        raise ValueError('Decoded scene differs from selected source scenario')
    if lighting_quality not in {'none','direct_only','draft'}:
        raise ValueError('Unsupported environment lighting quality')
    if not isinstance(bsps,list) or len(bsps)!=len(selection['bsps']):
        raise ValueError('Every selected BSP must have exactly one decoded payload')
    problems, bsp_plans, sky_plans, light_plans, design_plans = [], [], [], [], []
    sources = {selection['source_scenario']}
    for chosen,bsp in zip(selection['bsps'],bsps):
        if bsp['source_tag']!=chosen['source_tag'] or bsp['bsp_index']!=chosen['source_index']:
            raise ValueError('Decoded BSP identity differs from selected zone-set relationship')
        sources.add(bsp['source_tag'])
        problems.extend(authoring.audit_bsp(bsp))
        a=bsp['environment_semantics'].get('authoring')
        if not a:
            continue
        instances, errors = authoring.instance_plan(bsp); problems.extend(errors)
        portals, errors = authoring.portal_plan(bsp); problems.extend(errors)
        source_lighting=chosen['lighting_info']
        lights,errors=authoring.static_lighting(lighting_xmls[source_lighting],source_lighting)
        problems.extend(errors);light_plans.append(lights);sources.add(source_lighting)
        region=f'{paths.asset}_bsp_{chosen["source_index"]:04}'
        design=None
        if chosen['structure_design']:
            source=chosen['structure_design'];sources.add(source)
            design,errors=authoring.design_plan(designs[source],source,scenario_xml);problems.extend(errors)
            design.update(destination=f'{paths.namespace}/{region}.structure_design',region=region,
                          source_bsp_index=chosen['source_index'],target_bsp_index=chosen['target_index'])
            design_plans.append(design)
        # The structure collision sky encoding is only unique with one source sky.
        visible=sorted({i for i in bsp['environment_semantics']['cluster_sky_indices'] if i>=0})
        if len(visible)>1:
            problems.append(authoring.issue(bsp['source_tag'],'cluster sky/surface association',visible,
                                            'Multiple source skies require per-surface cluster resolution'))
        mapped=map_collision(bsp,sky_index=max(chosen['target_sky_index'],0))
        base=dict(mapped)
        # Source placements are retained separately, with shared local definitions.
        base['instances']=[r for r in mapped['instances'] if r['object']==-1 or
                           r['name'].startswith('cluster_') or r['name']=='@CollideOnly']
        meshes,omitted=bsp_meshes(base)
        materials=mapped['materials']
        for i, material in enumerate(materials):
            if i<len(a['materials']):
                imported=a['materials'][i]['imported material index']
                if not 0<=imported<len(lights['source_semantics']['materials']):
                    problems.append(authoring.issue(bsp['source_tag'],'materials[].imported material index',[i],
                                                   'Invalid source lighting material relationship',source_value=imported))
                else:
                    material['source_lighting_index']=imported
                    material['lighting']=lights['source_semantics']['materials'][imported]
        bsp_plans.append(dict(source_tag=bsp['source_tag'],source_index=chosen['source_index'],region=region,
            target_index=chosen['target_index'],destination=f'{paths.namespace}/{region}.scenario_structure_bsp',
            default_sky=chosen['target_sky_index'],materials=materials,meshes=meshes,omitted=omitted,
            instance_plan=instances,geometry_source=dict(file=f'geometry/bsp_{chosen["source_index"]:04}.json',
                canonical_sha256=stable_hash(bsp),object_count=len(bsp['objects']),
                definitions=[dict(source_index=d['source_index'],mesh_index=d['mesh index'],
                    collision_vertices=len(d.get('collision_mesh',{}).get('vertices',[])),
                    collision_triangles=len(d.get('collision_mesh',{}).get('triangles',[]))) for d in a['definitions']]),
            authoring={k:v for k,v in a.items() if k!='definitions'},portals=portals,structure_design=design,
            collision_semantics={k:v for k,v in bsp['environment_semantics'].items() if k!='authoring'},source_render=geometry_stats([m for m in meshes if m['role']=='render']),
            source_collision=geometry_stats([m for m in meshes if m['role']=='collision'])))
    for chosen,sky in zip(selection['skies'],skies):
        source=chosen['source_tag']
        if sky.get('source_tag')!=source:
            raise ValueError('Decoded sky differs from source palette identity')
        sources.update([source,*sky['dependencies'].values()])
        mesh=deepcopy(sky['render']);validate_mesh(mesh,len(mesh['materials']))
        nodes=mesh['nodes']
        if len(nodes)!=1 or nodes[0]['parent']!=-1 or any(nodes[0]['position']) or any(abs(x)>1e-6 for x in nodes[0]['rotation'][1:]):
            problems.append(authoring.issue(source,'render model nodes',list(range(len(nodes))),'Unmapped sky skeleton transform'))
        materials=[]
        for m in mesh['materials']:
            matches=[p for p in sky['shader_paths'] if p.rsplit('/',1)[1].rsplit('.',1)[0]==m['name']]
            if len(matches)!=1: raise ValueError('Ambiguous source sky shader identity')
            materials.append(matches[0])
        name=f'{paths.asset}_sky_{chosen["source_index"]:02}'
        sky_plans.append(dict(source_scenery=source,source_model=sky['dependencies']['model'],
            source_render_model=sky['dependencies']['render_model'],source_index=chosen['source_index'],
            target_index=chosen['target_index'],active_bsp_mask=chosen['active_bsp_mask'],
            source_object_fields=fixtures.fields(sky_xmls[source]),mesh=mesh,materials=materials,
            source_geometry=geometry_stats([mesh]),lighting=sky_lighting(sky_render_xmls[source]),
            destination=f'{paths.namespace}/sky/{name}/{name}.scenery',
            target_defaults=dict(imposter_policy='never',imposter_model='Unused Tool-authored placeholder')))
    seams=[]
    if selection['structure_seams']:
        sources.add(selection['structure_seams'])
        seams,errors=authoring.seam_plan(seams_xml,bsps);problems.extend(errors)
    materials=[];bitmaps={}
    dependency_audit = shaders.get('environment_dependencies', {})
    problems.extend(dependency_audit.get('unsupported', []))
    unresolved_bitmaps = {r['source_bitmap'] for r in dependency_audit.get('missing_references', [])
                          if r['classification'] == 'ACTIVE_REFERENCE_UNRESOLVED'}
    for source,shader in sorted(shaders['shaders'].items()):
        sources.add(source)
        if shader.get('status')!='resolved_snapshot' or shader.get('group')!='rmsh':
            problems.append(authoring.issue(source,'shader group/status',[source],
                'Native ReachStager currently supports rmsh; retain terrain recipes without substituting grey',
                source_value=dict(group=shader.get('group'),status=shader.get('status'))))
        runtime=[p['name'] for p in shader.get('parameters',[]) if p.get('has_functions') or p.get('extern')]
        if runtime: problems.append(authoring.issue(source,'parameters[].functions/extern',runtime,
            'Source material functions/externs require static-versus-runtime classification'))
        stem=source.rsplit('/',1)[1].rsplit('.',1)[0]
        materials.append(dict(source_shader=source,source_parameters=shader.get('parameters',[]),
            source_categories=shader.get('categories',[]),destination=paths.namespace+'/shaders/'+stem+'_'+stable_hash(source)[:8]+'.shader',
            strategy='Canonical source shader -> ReachStager -> native Foundry material and shader',classification='GENERATED'))
    for key,bitmap in sorted(shaders['bitmaps'].items()):
        source=relative(bitmap['path']).as_posix()+'.bitmap';sources.add(source)
        if source in unresolved_bitmaps:
            continue  # The usage/cache audit owns this error; absence is not an image-form error.
        try:bitmaps[key]=dict(bitmap_strategy(bitmap),source_bitmap=bitmap['path'],index=bitmap['index'])
        except ValueError as exc: problems.append(authoring.issue(source,'bitmap image form',[key],str(exc),
            source_value={k:bitmap.get(k) for k in ('type','depth','image_count','index','format')}))
    # Scenario light volumes remain distinct from BSP generic static lights.
    scenario_lights,errors=authoring.scenario_light_plan(scenario_xml,selection,light_xmls)
    problems.extend(errors)
    sources.update(p['source_tag'] for p in scenario_lights['palette'] if p['source_tag'])
    mapping_file=__import__('pathlib').Path(__file__).with_name('mappings.json')
    catalog=json.loads(mapping_file.read_text(encoding='utf-8'))
    source_hashes={}
    for source in sorted(s for s in sources if s):
        try:source_hashes[source]=digest(paths.source(source))
        except FileNotFoundError:
            if source not in unresolved_bitmaps:
                problems.append(authoring.issue(source,'source file/SHA-256',[source],
                    'Source identity has no loose hash; dependency usage and recovery classification remain required'))
    result=dict(format=FORMAT,version=2,builder_version=BUILDER_VERSION,
        source=dict(game='halo3_mcc',scenario=selection['source_scenario'],hashes=source_hashes),
        target=dict(game='haloreach_mcc',namespace=paths.namespace,scenario=paths.scenario+'.scenario',
                    project_fingerprint=paths.fingerprint(),units='ass_100_per_world_unit',scene_scale='max',forward_direction='x'),
        selection=selection,bsps=bsp_plans,skies=sky_plans,structure_designs=design_plans,seams=seams,
        materials=materials,bitmaps=bitmaps,lighting_by_bsp=light_plans,scenario_lights=scenario_lights,unsupported=problems,
        source_dependencies=dependency_audit,
        scenario=dict(source_semantics=fixtures.scenario_semantics(scenario_xml),spawn=selection['spawn'] or spawn_above_collision([m for b in bsp_plans for m in b['meshes']]),
                      type='solo',zone_set=selection['source_zone_set'],active_bsp_mask=selection['target_bsp_mask'],
                      structure_designs=[d['destination'] for d in design_plans],defaults=dict(custom_gravity_scale=1.0)),
        mappings_used=[*catalog['campaign_shared_rule_ids'],*(r['id'] for r in catalog['campaign_rules'])],
        mapping_catalog_sha256=digest(mapping_file),
        excluded=['normal scenario objects','AI','HSC','audio','effects','cinematics','source runtime resources'],
        unknowns=['Nate must confirm runtime acceptance after a successful native build.'])
    result['lighting']=dict(source_tag=light_plans[0]['source_tag'],sky=sky_plans[0]['lighting'],quality=lighting_quality)
    result['plan_sha256']=stable_hash(result)
    return result

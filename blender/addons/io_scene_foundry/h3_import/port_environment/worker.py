"""Background Blender build worker. This file never implements a Reach exporter."""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import sys
import time
import tomllib
import traceback
from types import SimpleNamespace
from zipfile import ZipFile

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = 'port_environment'

from . import BUILDER_VERSION
from . import fixtures
from .model import stable_hash, plan_bsps, plan_skies
from .paths import OutputPaths, atomic_json, digest, relative
from .validation import NATIVE_TAG_EXTENSIONS, geometry_errors, lighting_evidence, lighting_count_errors


def dependencies(addon, run):
    """Extract this package's bundled wheels into this worker's isolated directory."""
    target = run/'python-dependencies'
    target.mkdir()
    hashes = {}
    for wheel in sorted((addon/'wheels').glob('*.whl')):
        hashes[wheel.name] = digest(wheel)
        with ZipFile(wheel) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                name = relative(member.filename)
                path = target/name
                if not path.resolve().is_relative_to(target.resolve()):
                    raise ValueError('Bundled wheel path escapes dependency directory')
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open('xb') as stream:
                    stream.write(archive.read(member))
    sys.path.insert(0, str(target))
    return hashes


class ToolJournal:
    """Observe normal Foundry's subprocess boundary and reject out-of-scope jobs."""
    def __init__(self, paths, run, report, flush):
        from io_scene_foundry import utils
        self.paths, self.run, self.report, self.flush = paths, run, report, flush
        self.original = utils._popen_tool
        self.running = []
        utils._popen_tool = self.popen

    def check(self, command):
        command = [str(x) for x in command]
        if Path(command[0]).resolve() not in {self.paths.reach/'tool.exe', self.paths.reach/'tool_fast.exe'}:
            raise ValueError('Unexpected target executable: '+command[0])
        action = command[1]
        if action in {'import', 'reimport-bitmaps-single'}:
            arg = command[2].replace('\\', '/')
            if not arg.startswith(self.paths.namespace+'/'):
                raise ValueError('Tool output is outside the generated namespace: '+arg)
            for kind in ('data', 'tags'):
                self.paths.destination(kind)
        elif action == 'export-tag-to-xml':
            source, target = Path(command[2]).resolve(), Path(command[3]).resolve()
            if not source.is_relative_to(self.paths.destination('tags')) or not target.is_relative_to(self.run):
                raise ValueError('Tag validation XML path escapes this build')
        elif action.startswith('faux'):
            allowed = {'faux_data_sync', 'faux_farm_begin', 'faux_farm_dillum', 'faux_farm_dillum_merge',
                       'faux_farm_pcast', 'faux_farm_pcast_merge', 'faux_farm_radest_extillum',
                       'faux_farm_radest_extillum_merge', 'faux_farm_fgather', 'faux_farm_fgather_merge',
                       'faux_farm_finish', 'faux-reorganize-mesh-for-analytical-lights',
                       'faux-build-vmf-textures-from-quadratic'}
            if action not in allowed:
                raise ValueError('Unreviewed Faux invocation: '+action)
            from io_scene_foundry.tools.scenario.lightmap import calc_job_id
            scenario = self.paths.scenario.replace('/', '\\')
            blob = 'faux/'+str(calc_job_id(scenario, 'all'))
            first = command[2].replace('\\', '/')
            if first not in {self.paths.scenario, blob}:
                raise ValueError('Faux invocation belongs to a different job: '+first)
            if action == 'faux_farm_begin' and command[5] not in {'direct_only', 'draft'}:
                raise ValueError('Only direct_only/draft lighting is allowed')
        else:
            # In particular, do not let missing shader templates cause writes
            # under the shared stock shader namespace. Existing Reach templates
            # are read-only infrastructure; a missing one is an explicit blocker.
            raise ValueError('Unreviewed/out-of-namespace Tool operation: '+action)
        return command

    def popen(self, command, cwd, **kwargs):
        self.finish()
        command = self.check(command)
        row = dict(command=command, cwd=str(cwd), status='RUNNING', started=time.time(),
                   log=str(self.run/'blender-reach-worker.log'))
        stream = kwargs.get('stdout')
        stream_name = getattr(stream, 'name', None)
        if isinstance(stream_name, str) and not stream_name.startswith('<'):
            row['source_log'] = str(Path(cwd, stream_name).resolve())
        self.report['tool_invocations'].append(row)
        self.flush()
        process = self.original(command, cwd, **kwargs)
        self.running.append((process, row, time.perf_counter()))
        return process

    def finish(self, wait=False):
        still = []
        for process, row, start in self.running:
            code = process.wait() if wait else process.poll()
            if code is None:
                still.append((process, row, start))
            else:
                row.update(exit_code=code, seconds=time.perf_counter()-start,
                           status='ACCEPTED' if code == 0 else 'FAILED')
                if row.get('source_log') and Path(row['source_log']).is_file():
                    folder = self.run/'tool-logs'
                    folder.mkdir(exist_ok=True)
                    copy = folder/(f"{self.report['tool_invocations'].index(row):04d}.log")
                    with copy.open('xb') as stream:
                        stream.write(Path(row['source_log']).read_bytes())
                    row['log'] = str(copy)
        self.running = still


def protect_tag_writes(paths):
    from io_scene_foundry.managed_blam import Tag
    original_init, original_exit = Tag.__init__, Tag.__exit__

    def check(tag):
        name = str(tag.tag_path.RelativePathWithExtension).replace('\\', '/')
        if not name.startswith(paths.namespace+'/'):
            raise ValueError('Refusing ManagedBlam write outside compiler namespace: '+name)
        expected = paths.destination('tags', name[len(paths.namespace)+1:])
        if Path(str(tag.tag_path.Filename)).resolve() != expected:
            raise ValueError('ManagedBlam target resolves to a different project: '+str(tag.tag_path.Filename))

    def init(tag, *args, **kwargs):
        original_init(tag, *args, **kwargs)
        if tag.tag_is_new:
            try:
                check(tag)
            except Exception:
                tag.tag.Dispose()
                raise

    def close(tag, exc_type, exc_value, tb):
        if tag.tag and (tag.tag_has_changes or tag.always_save):
            check(tag)
        return original_exit(tag, exc_type, exc_value, tb)

    Tag.__init__, Tag.__exit__ = init, close


def setup_scene(name, asset_type, sidecar, region, project):
    import bpy
    from io_scene_foundry import utils
    scene = bpy.data.scenes.new(name)
    bpy.context.window.scene = scene
    nwo = utils.get_scene_props()
    nwo.scene_project = project
    nwo.asset_type = asset_type
    nwo.scale = 'max'
    nwo.forward_direction = 'x'
    nwo.sidecar_path = sidecar.replace('/', '\\')
    nwo.regions_table.clear()
    nwo.regions_table.add().name = region
    nwo.permutations_table.clear()
    nwo.permutations_table.add().name = 'default'
    nwo.template_scenario = ''
    nwo.scenario_type = 'solo'
    settings = utils.get_export_props()
    settings.export_mode = 'FULL'
    settings.event_level = 'DEFAULT'
    settings.lightmap_structure = False
    settings.create_debug_zone_set = False
    settings.export_all_bsps = 'all'
    settings.export_all_perms = 'all'
    return scene


def mesh_object(record, materials, scene, region, name, role='render'):
    import bpy
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([v['position'] for v in record['vertices']], [], [t['vertices'] for t in record['triangles']])
    mesh.update()
    for material in materials:
        mesh.materials.append(material)
    mesh.polygons.foreach_set('material_index', [t['material'] for t in record['triangles']])
    mesh.polygons.foreach_set('use_smooth', [True]*len(mesh.polygons))
    mesh.normals_split_custom_set_from_vertices([v['normal'] for v in record['vertices']])
    channels = max(len(v.get('uvs', [])) for v in record['vertices'])
    for index in range(channels):
        layer = mesh.uv_layers.new(name='UVMap' if not index else f'UVMap.{index:03}')
        layer.data.foreach_set('uv', [component for loop in mesh.loops
            for component in (record['vertices'][loop.vertex_index]['uvs'][index][:2]
                              if len(record['vertices'][loop.vertex_index].get('uvs', [])) > index else [0,0])])
    if all(v.get('color') is not None for v in record['vertices']):
        attr = mesh.color_attributes.new(name='Color', type='FLOAT_COLOR', domain='POINT')
        attr.data.foreach_set('color', [n for v in record['vertices'] for n in [*v['color'][:3],1]])
    mesh.nwo.mesh_type = record.get('mesh_type', '_connected_geometry_mesh_type_default')
    if record.get('face_mode'):
        prop = mesh.nwo.face_props.add()
        prop.type = 'face_mode'
        prop.face_mode = record['face_mode']
        attribute = mesh.attributes.new(name='h3_port_face_mode', type='BOOLEAN', domain='FACE')
        mask = [t.get('surface_type') != 'sky' for t in record['triangles']]
        attribute.data.foreach_set('value', mask)
        prop.attribute_name = attribute.name
        prop.face_count = sum(mask)
    ob = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(ob)
    ob.nwo.export_this = True
    ob.nwo.region_name = region
    ob.nwo.permutation_name = 'default'
    ob['h3_port_role'] = role
    # Check actual Blender data, not a copy of the expected statistics.
    if len(mesh.vertices) != len(record['vertices']) or len(mesh.polygons) != len(record['triangles']):
        raise ValueError('Blender source topology changed during construction')
    error = max(abs(v.co[i]-r['position'][i]) for v, r in zip(mesh.vertices, record['vertices']) for i in range(3))
    if error > 0.01:  # float32 rounding at the large H3 sky radius, in ASS units
        raise ValueError('Blender source coordinates changed beyond float32 tolerance')
    if [tuple(p.vertices) for p in mesh.polygons] != [tuple(t['vertices']) for t in record['triangles']]:
        raise ValueError('Blender source triangle order/winding changed')
    return ob, dict(name=name, vertices=len(mesh.vertices), triangles=len(mesh.polygons),
                    bounds_world=[[min(v.co[i] for v in mesh.vertices)/100 for i in range(3)],
                                  [max(v.co[i] for v in mesh.vertices)/100 for i in range(3)]],
                    maximum_coordinate_rounding_ass=error, role=role)


def materials(plan, config, paths, report):
    import bpy
    from io_scene_foundry.h3_import.reach_builder import ReachStager
    from io_scene_foundry.tools.export_bitmaps import export_bitmap
    from io_scene_foundry.tools.shader_builder import build_shader
    source_dir = Path(config['source_directory'])
    manifest_path = (source_dir/relative(config.get('shader_manifest', 'shader_manifest.json'))).resolve(strict=True)
    if not manifest_path.is_relative_to(source_dir.resolve()):
        raise ValueError('Authoring shader manifest escapes extraction directory')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    adapted = deepcopy(manifest)
    source_images = {}
    for key, bitmap in manifest['bitmaps'].items():
        source_path = (source_dir/relative(plan['bitmaps'][key]['source_image'])).resolve(strict=True)
        if not source_path.is_relative_to(source_dir):
            raise ValueError('Source bitmap escapes extraction directory')
        image = bpy.data.images.load(str(source_path), check_existing=False)
        if tuple(image.size) != (bitmap['width'], bitmap['height']) or not image.has_data:
            raise ValueError('Blender could not decode source bitmap pixels: '+str(source_path))
        image['h3_source_bitmap'] = bitmap['path']
        image['h3_bitmap_index'] = bitmap['index']
        image.pack()
        source_images[key] = image
        # ReachStager consumes already-loaded source pixels. Its source manifest
        # remains independent from the target shader/image identities.
        adapted['bitmaps'][key]['preview'] = plan['bitmaps'][key]['source_image']
    text = bpy.data.texts.new('H3 proof source shader snapshots')
    text.write(json.dumps(adapted))
    stager = ReachStager()
    result = {}
    for row in plan['materials']:
        source = bpy.data.materials.new('source_'+Path(row['destination']).stem)
        source.use_nodes = True
        source['h3_source_shader'] = row['source_shader']
        source['h3_source_object'] = manifest['source_tag']
        source['h3_shader_manifest'] = text.name
        for p in row['source_parameters']:
            if p.get('bitmap') in source_images:
                source.node_tree.nodes.new('ShaderNodeTexImage').image = source_images[p['bitmap']]
        target = stager.build(source)
        if target is None:
            raise ValueError('Reach material staging failed: '+json.dumps(stager.results[-1]))
        mapped = {p['name']: p['status'] for p in stager.results[-1]['parameters']}
        for p in row['source_parameters']:
            if p['type'] == 'bitmap' and mapped.get(p['name']) != 'mapped':
                raise ValueError('Required source bitmap was not mapped to a Reach socket: '+p['name'])
        target.nwo.shader_path = row['destination'].replace('/', '\\')
        result[row['source_shader']] = target
    # Export each usage-specific staged image once; several shaders share the
    # concrete detail and default textures. The ordinary shader writer sees
    # existing target identities and does not rebuild these bitmap tags.
    for image in dict.fromkeys(stager.images.values()):
        # Image.copy retains packed bytes but Blender loads the copied buffer
        # lazily. Foundry's bitmap exporter intentionally checks has_data first.
        if len(image.pixels) != image.size[0]*image.size[1]*4 or not image.has_data:
            raise ValueError('Staged image cannot load its packed source pixels: '+image.name)
        bitmap_path = export_bitmap(image)
        if not bitmap_path or not (paths.roots['tags']/bitmap_path).is_file():
            raise ValueError('Reach bitmap import did not produce a tag for '+image.name)
    for target in result.values():
        build_shader(target, False)
    report['material_staging'] = stager.results
    report['bitmap_builds'] = [dict(name=i.name, destination=i.nwo.filepath,
                                  source_bitmap=i.get('h3_source_bitmap')) for i in dict.fromkeys(stager.images.values())]
    return result


def sky_lights(scene, plan):
    import bpy
    from mathutils import Vector
    from io_scene_foundry import utils
    spec = plan['lighting']['sky']
    for i, sample in enumerate(spec['source_samples']):
        last = i == len(spec['source_samples'])-1
        name = 'zz_h3_sun' if last else f'h3_skylight_{i:04}'
        data = bpy.data.lights.new(name, 'SUN')
        if last:
            intensity = Vector(spec['sun_irradiance'])
            data.color = intensity.normalized()
            data.energy = intensity.length/2
        else:
            data.color = sample['intensity']
            data.energy = sample['solid_angle']
        ob = bpy.data.objects.new(name, data)
        scene.collection.objects.link(ob)
        ob.rotation_mode = 'QUATERNION'
        ob.rotation_quaternion = Vector(sample['direction']).to_track_quat('Z','Y')
        ob.nwo.export_this = True
        ob.nwo.region_name = 'default'
        ob.nwo.permutation_name = 'default'
        ob['h3_port_classification'] = 'GENERATED'
        ob['h3_sky_sample'] = i
    nwo = utils.get_scene_props()
    nwo.sun_size = spec['sun_size_degrees']
    nwo.sun_as_vmf_light = False
    nwo.sun_bounce_scale = spec['defaults']['sun_bounce_scale']
    nwo.skylight_bounce_scale = spec['defaults']['skylight_bounce_scale']
    bpy.context.view_layer.update()


def export(scene, paths, relative_asset, name):
    import bpy
    from io_scene_foundry import utils
    from io_scene_foundry.export import export_asset
    bpy.context.window.scene = scene
    nwo = utils.get_scene_props()
    target = paths.destination('data', relative_asset[len(paths.namespace)+1:] if relative_asset != paths.namespace else '')
    target.mkdir(parents=True, exist_ok=True)
    blend = target/(name+'.blend')
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), check_existing=False)
    sidecar = relative_asset+'/'+name+'.sidecar.xml'
    export_asset(bpy.context, str(target/(name+'.sidecar.xml')), sidecar.replace('/', '\\'), name,
                 str(target), nwo, utils.get_export_props(), False, False, True)
    if not (target/(name+'.sidecar.xml')).is_file() or not list((target/'export').rglob('*.gr2')):
        raise ValueError('Foundry did not produce the expected sidecar and GR2 source')


def configure_scenario(paths, plan):
    from io_scene_foundry.managed_blam.scenario import ScenarioTag
    path = plan['target']['scenario'].replace('/', '\\')
    with ScenarioTag(path=path) as tag:
        if not tag.block_bsps.Elements.Count:
            bsp = tag.block_bsps.AddElement()
            bsp.SelectField('structure bsp').Path = tag._TagPath_from_string(plan['bsp']['destination'])
        if tag.block_bsps.Elements.Count != 1:
            raise ValueError('Generated scenario must contain exactly one BSP')
        bsp = tag.block_bsps.Elements[0]
        bsp.SelectField('size class').SetValue('1Meg_512x512')
        bsp.SelectField('custom gravity scale').Data = 1.0
        if not tag.block_skies.Elements.Count:
            tag.add_new_sky(plan['sky']['destination'])
        if tag.block_skies.Elements.Count != 1:
            raise ValueError('Generated scenario must contain exactly one sky')
        bsp.SelectField('default sky').Value = 0
        sky = tag.block_skies.Elements[0]
        for name in ('cloud scale', 'cloud speed', 'cloud direction'):
            sky.SelectField(name).Data = 0.0
        active = sky.SelectField('active on bsps')
        for index, item in enumerate(active.Items):
            item.IsSet = index == 0
        if not tag.block_zone_sets.Elements.Count:
            zone = tag.block_zone_sets.AddElement()
            zone.SelectField('name').SetStringData(plan['scenario']['zone_set'])
            for name in ('pvs index', 'hint previous zone set', 'audibility index'):
                zone.SelectField(name).Value = -1
            for index, item in enumerate(zone.SelectField('bsp zone flags').Items):
                item.IsSet = index == 0
        starts = tag.tag.SelectField('Block:player starting locations')
        if not starts.Elements.Count:
            tag.create_default_profile()
        start = starts.Elements[0]
        start.SelectField('position').Data = plan['scenario']['spawn']['position_world']
        start.SelectField('facing').Data = plan['scenario']['spawn']['facing_degrees']
        tag.tag_has_changes = True
        # Preserve the actual Save failure before the generic context manager
        # can turn it into console output; native readback follows export.
        tag.tag.Save()


def configure_sky_model(plan):
    from io_scene_foundry.managed_blam.model import ModelTag
    with ModelTag(path=plan['sky']['destination'].rsplit('.',1)[0]+'.model', tag_must_exist=True) as tag:
        tag.tag.SelectField('ShortEnum:imposter policy').SetValue('never')
        tag.tag_has_changes = True
        # Explicit Save exposes an error that the generic context manager could
        # otherwise suppress. Later readback verifies actual native tag contents.
        tag.tag.Save()


def validate_lighting_inputs(plan, report):
    """Read native authoring tags before Faux, without creating or editing tags."""
    from io_scene_foundry.managed_blam import Tag
    source = dict(sky_samples=0, light_definitions=0, light_instances=0, emissive_rows=0)
    native = dict(source, sky_energy=0.0)
    rows, errors = [], []
    for sky in plan_skies(plan):
        spec = sky.get('lighting', plan['lighting']['sky'])
        source['sky_samples'] += len(spec['source_samples'])
        path = sky['destination'].rsplit('.', 1)[0]+'.render_model'
        with Tag(path=path, tag_must_exist=True) as tag:
            samples = tag.tag.SelectField('Block:sky lights')
            count, energy = samples.Elements.Count, 0.0
            for sample in samples.Elements:
                color = list(sample.SelectField('intensity').Data)
                angle = sample.SelectField('solid angle').Data
                if not all(math.isfinite(v) and v >= 0 for v in [*color, angle]):
                    raise ValueError('Nonfinite/negative native sky lighting input: '+path)
                energy += sum(color)*angle
            native['sky_samples'] += count
            native['sky_energy'] += energy
            expected = dict(sky_samples=len(spec['source_samples']), light_definitions=0, light_instances=0, emissive_rows=0)
            written = dict(expected, sky_samples=count, sky_energy=energy)
            errors.extend(path+': '+error for error in lighting_count_errors(expected, written))
            rows.append(dict(path=path, sky_samples=count, sky_energy=energy))
    lights = plan.get('lighting_by_bsp', [plan['lighting']])
    if len(lights) != len(plan_bsps(plan)):
        raise ValueError('Lighting source/BSP relationship is incomplete')
    for bsp, light in zip(plan_bsps(plan), lights):
        semantics = light['source_semantics']
        source['light_definitions'] += len(semantics['light_definitions'])
        source['light_instances'] += len(semantics['light_instances'])
        source['emissive_rows'] += sum(float(m['emissive power']) != 0 for m in semantics['materials'])
        path = bsp['destination'].rsplit('.', 1)[0]+'.scenario_structure_lighting_info'
        with Tag(path=path, tag_must_exist=True) as tag:
            definitions = tag.tag.SelectField('Block:generic light definitions').Elements.Count
            instances = tag.tag.SelectField('Block:generic light instances').Elements.Count
            materials = tag.tag.SelectField('Block:material info').Elements
            powers = [m.SelectField('emissive power').Data for m in materials]
            if any(not math.isfinite(v) or v < 0 for v in powers):
                raise ValueError('Nonfinite/negative native material emission: '+path)
            emissive = sum(v > 0 for v in powers)
            native['light_definitions'] += definitions
            native['light_instances'] += instances
            native['emissive_rows'] += emissive
            expected = dict(sky_samples=0, light_definitions=len(semantics['light_definitions']),
                            light_instances=len(semantics['light_instances']),
                            emissive_rows=sum(float(m['emissive power']) != 0 for m in semantics['materials']))
            written = dict(sky_samples=0, sky_energy=0, light_definitions=definitions, light_instances=instances,
                           emissive_rows=emissive)
            errors.extend(path+': '+error for error in lighting_count_errors(expected, written))
            rows.append(dict(path=path, light_definitions=definitions, light_instances=instances,
                             emissive_rows=emissive))
    report['lighting_input_readback'] = dict(source=source, native=native, tags=rows, errors=errors,
        status='REJECTED' if errors else 'NATIVE_COUNTS_VERIFIED_BEFORE_FAUX',
        limitation='Counts and nonzero sky energy; not a claim of photometric or surface-mapping parity')
    if errors:
        raise ValueError('Lighting inputs rejected before Faux: '+errors[0])


def validate_native(paths, plan, run, report):
    from io_scene_foundry.managed_blam import Tag
    from io_scene_foundry import utils
    from io_scene_foundry.managed_blam.scenario import ScenarioTag
    with ScenarioTag(path=plan['target']['scenario'], tag_must_exist=True) as tag:
        actual_bsp = tag.block_bsps.Elements[0].SelectField('structure bsp').Path.RelativePathWithExtension.replace('\\','/')
        actual_sky = tag.block_skies.Elements[0].SelectField('sky').Path.RelativePathWithExtension.replace('\\','/')
        if actual_bsp != plan['bsp']['destination'] or actual_sky != plan['sky']['destination']:
            raise ValueError('Native scenario points to an unexpected environment or sky')
        if tag.block_bsps.Elements.Count != 1 or tag.block_skies.Elements.Count != 1:
            raise ValueError('Native BSP/sky count differs from the compiler plan')
        starts = tag.tag.SelectField('Block:player starting locations')
        if not starts.Elements.Count or not tag.block_zone_sets.Elements.Count:
            raise ValueError('Native scenario lacks player-start/zone-set authoring')
        report['scenario_readback'] = dict(bsp=actual_bsp, sky=actual_sky,
            player_position=list(starts.Elements[0].SelectField('position').Data),
            default_sky=tag.block_bsps.Elements[0].SelectField('default sky').Value,
            zone_sets=tag.block_zone_sets.Elements.Count)
    with Tag(path=plan['bsp']['destination'], tag_must_exist=True) as tag:
        clusters = tag.tag.SelectField('Block:clusters')
        indices = [e.SelectField('scenario sky index').Data for e in clusters.Elements]
        if indices != [0]:
            raise ValueError('Generated Reach cluster is not associated with the generated sky')
        report['cluster_sky_indices'] = indices
    with Tag(path=plan['sky']['destination'].rsplit('.',1)[0]+'.render_model', tag_must_exist=True) as tag:
        count = tag.tag.SelectField('Block:sky lights').Elements.Count
        values = [e.Fields[0].Data for e in tag.tag.SelectField('Array:sun').Elements]
        expected = plan['lighting']['sky']
        if count != len(expected['source_samples']) or len(values) != 6 or any(
                abs(a-b) > .0001 for a,b in zip(values[3:],expected['sun_irradiance'])):
            raise ValueError('Native sky lighting differs from the source authoring plan')
        report['sky_lighting_readback'] = dict(samples=count, sun_direction_and_intensity=values)
    with Tag(path=plan['sky']['destination'].rsplit('.',1)[0]+'.model', tag_must_exist=True) as tag:
        policy = tag.tag.SelectField('ShortEnum:imposter policy')
        if str(policy.Items[policy.Value].EnumName) != 'never':
            raise ValueError('Generated sky model still requires an ungenerated imposter asset')
        report['sky_imposter_policy'] = 'never'
    output = run/'native-tag-xml'
    output.mkdir()
    references = set()
    report['native_reference_details'] = []
    report['optional_native_placeholders'] = []
    report['auxiliary_outputs_without_xml_validation'] = []
    for index, source in enumerate(sorted(paths.destination('tags').rglob('*'))):
        if not source.is_file():
            continue
        if source.suffix not in NATIVE_TAG_EXTENSIONS:
            report['auxiliary_outputs_without_xml_validation'].append(dict(path=str(source),
                reason='Not a required authoring tag group; raw output is hashed, native XML validation is unresolved'))
            continue
        # Foundation XML uses display names. Read full runtime identities from
        # ManagedBlam; do not infer them from XML labels.
        with Tag(path=str(source), tag_must_exist=True) as tag:
            for field in tag.tag.SelectTagFieldReferencesFast():
                if field.Path is None:
                    continue
                name = str(field.Path.RelativePathWithExtension).replace('\\','/')
                absolute = Path(str(field.Path.Filename)).resolve()
                if not absolute.is_relative_to(paths.roots['tags']):
                    raise ValueError('Foreign native reference: '+name)
                if not absolute.is_file():
                    # Both the supplied Reach oracle and live stock box have
                    # this Tool-authored reference but no asset, with zero
                    # instances. Preserve that compiler output; do not fabricate
                    # an imposter resource or broadly permit missing references.
                    optional_bsp = (source.suffix == '.scenario_structure_bsp'
                        and name == plan['bsp']['destination'].rsplit('.',1)[0]+'.instance_imposter_definition'
                        and tag.tag.SelectField('Block:instanced geometry instances').Elements.Count == 0)
                    optional_sky = (source.suffix == '.model'
                        and name == plan['sky']['destination'].rsplit('.',1)[0]+'.imposter_model'
                        and tag.tag.SelectField('ShortEnum:imposter policy').Value == 1)
                    if optional_bsp or optional_sky:
                        report['optional_native_placeholders'].append(dict(reference=name, classification='UNRESOLVED',
                            reason=('Tool-authored imposter reference for zero instances; paired/live stock Reach box has the same missing-asset shape'
                                if optional_bsp else 'Tool regenerates this placeholder even after clearing it; native sky imposter policy is never; generated render model is required'),
                            runtime_status='PENDING_NATE'))
                        continue
                    raise ValueError('Missing/foreign native reference: '+name)
                generated = name.startswith(paths.namespace+'/')
                if name.startswith('levels/') and not generated:
                    raise ValueError('Generated tag depends on a stock environment: '+name)
                report['native_reference_details'].append(dict(owner=source.relative_to(paths.roots['tags']).as_posix(),
                    field=str(field.FieldPath), reference=name,
                    classification='GENERATED' if generated else 'TARGET_DEFAULT'))
        target = output/(f'{index:04}_'+source.name+'.xml')
        utils.run_tool(['export-tag-to-xml', str(source), str(target)], force_tool=True)
        if not target.is_file():
            raise ValueError('Reach Tool could not open generated tag: '+str(source))
        root = fixtures.parse(target.read_bytes())
        for field in root.iter('field'):
            if field.get('type') != 'tag reference':
                continue
            value = field.get('value', '').split(',', 1)[0].replace('\\','/')
            if not value:
                continue
            if ':' in value or value.startswith('/') or value.lower().startswith('levels/test/box'):
                raise ValueError('Foreign/stock-box reference in generated Reach tag: '+value)
            references.add(value)
    report['runtime_references'] = sorted(references)
    report['native_tag_open_status'] = 'MANAGEDBLAM_AND_REACH_TOOL_OPENED'


def main():
    config_path = Path(sys.argv[sys.argv.index('--')+1]).resolve(strict=True)
    config = json.loads(config_path.read_text(encoding='utf-8'))
    run = Path(config['run_directory']).resolve(strict=True)
    plan = json.loads(Path(config['plan']).read_text(encoding='utf-8'))
    # Campaign plans currently stop at unresolved source contracts. Never let a
    # schema-2 multi-BSP plan fall through the regression writer's single-BSP
    # assumptions or create partial target assets before that boundary is explicit.
    if plan.get('unsupported'):
        raise ValueError('Native authoring refused: unresolved source semantics in environment plan')
    if plan.get('version') != 1:
        raise ValueError('Native authoring for campaign plan schema 2 is not yet implemented; no target writes were attempted')
    paths = OutputPaths(config['h3_root'], config['reach_root'], config['namespace'])
    expected_hash = plan.pop('plan_sha256')
    if stable_hash(plan) != expected_hash or expected_hash != config['plan_sha256']:
        raise ValueError('Worker plan integrity mismatch')
    plan['plan_sha256'] = expected_hash
    if plan['target']['project_fingerprint'] != paths.fingerprint():
        raise ValueError('Worker plan belongs to a different Reach root')
    for source, sha in plan['source']['hashes'].items():
        if digest(paths.source(source)) != sha:
            raise ValueError('Source changed after planning: '+source)
    addon = Path(__file__).resolve().parents[2]
    report = dict(format='foundry.h3-reach-environment.worker', version=1, builder_version=BUILDER_VERSION,
                  status='BUILDING', stage='bootstrap', tool_invocations=[], geometry=[], lighting_status='NOT_RUN')
    flush = lambda: atomic_json(run/'worker-report.json', report)
    journal, profile = None, None
    try:
        flush()
        report['bundled_dependencies'] = dependencies(addon, run)
        sys.path.insert(0, str(addon.parent))
        import bpy
        import io_scene_foundry
        from io_scene_foundry import startup
        load_projects = startup.load_projects
        # Bootstrap a transient worker project; never edit the saved project list.
        startup.load_projects = lambda: []
        try:
            bpy.ops.preferences.addon_enable(module='io_scene_foundry')
        finally:
            startup.load_projects = load_projects
        from io_scene_foundry import utils, managed_blam, foundry_output
        from io_scene_foundry.h3_import.scenario_reporting import Profile
        profile = Profile()
        # Extension discovery normally supplies this module metadata. A source
        # checkout enabled directly in a fresh background process has no entry
        # in addon_utils' extension repository scan.
        version = tomllib.loads((addon/'blender_manifest.toml').read_text(encoding='utf-8'))['version']
        if utils.module is None:
            utils.module = SimpleNamespace(bl_info={'version': tuple(int(n) for n in version.split('.'))})
        report['extension_version'] = version
        prefs = utils.get_prefs()
        prefs.projects.clear()
        project = prefs.projects.add()
        project.name = 'H3 Proof Reach Worker'
        project.project_path = str(paths.reach)
        project.project_xml = str(paths.reach/'project.xml')
        project.tags_directory = str(paths.roots['tags'])
        project.data_directory = str(paths.roots['data'])
        project.corinth = False
        prefs.tool_type = 'tool'
        prefs.link_resource_nodes = False
        foundry_output.child_stream = lambda: sys.stdout
        sky_asset = plan['sky']['destination'].rsplit('/', 1)[0]
        sky_name = 'proof_box_sky'
        sky_scene = setup_scene(sky_name, 'sky', sky_asset+'/'+sky_name+'.sidecar.xml', 'default', project.name)
        os.chdir(paths.reach)
        managed_blam.mb_init()
        if not managed_blam.mb_active:
            raise RuntimeError('Reach ManagedBlam did not initialize')
        protect_tag_writes(paths)
        journal = ToolJournal(paths, run, report, flush)
        report['stage'] = 'materials'
        flush()
        # Stage/export materials while the scenario asset is current so every
        # generated bitmap lives under the common proof namespace.
        scene = setup_scene(paths.asset, 'scenario', paths.scenario+'.sidecar.xml', 'proof_box_bsp', project.name)
        with profile.span('native Reach material and bitmap build'):
            mats = materials(plan, config, paths, report)
        report['stage'] = 'sky export'
        flush()
        bpy.context.window.scene = sky_scene
        with profile.span('H3 sky construction and normal Reach export'):
            _, stats = mesh_object(plan['sky']['mesh'], [mats[k] for k in plan['sky']['materials']],
                                   sky_scene, 'default', 'h3_sky')
            report['geometry'].append(stats)
            sky_lights(sky_scene, plan)
            export(sky_scene, paths, sky_asset, sky_name)
            configure_sky_model(plan)
        report['stage'] = 'BSP and scenario export'
        flush()
        bpy.context.window.scene = scene
        with profile.span('H3 BSP construction and normal Reach export'):
            bsp_materials = [mats.get(m['source_shader']) for m in plan['bsp']['materials']]
            # Auxiliary collision slot has no H3 shader. Its render is disabled;
            # use an owned native shader solely as a surface material definition.
            collision_material = mats[plan['materials'][0]['source_shader']]
            bsp_materials = [m or collision_material for m in bsp_materials]
            for i, material in enumerate(plan['bsp']['materials']):
                if material.get('special') == 'sky':
                    bsp_materials[i] = bpy.data.materials.new('+sky0')
            for index, record in enumerate(plan['bsp']['meshes']):
                _, stats = mesh_object(record, bsp_materials, scene, 'proof_box_bsp', 'h3_bsp_'+str(index), record['role'])
                report['geometry'].append(stats)
            configure_scenario(paths, plan)
            export(scene, paths, paths.namespace, paths.asset)
        journal.finish(wait=True)
        failed = [r for r in report['tool_invocations'] if r.get('exit_code')]
        if failed:
            raise RuntimeError('Reach Tool failed: '+json.dumps(failed[0]))
        sys.stdout.flush()
        errors = geometry_errors((run/'blender-reach-worker.log').read_text(encoding='utf-8', errors='replace'))
        report['geometry_tool_errors'] = errors
        if errors:
            raise RuntimeError(f'Reach Tool reported {len(errors)} geometry errors despite its exit code: {errors[0]}')
        report['stage'] = 'lighting input validation'
        flush()
        with profile.span('native lighting input validation before Faux'):
            validate_lighting_inputs(plan, report)
        report['stage'] = 'lighting'
        flush()
        if config['lighting'] != 'none':
            from io_scene_foundry.tools.scenario.lightmap import run_lightmapper
            with profile.span('normal Foundry Reach Faux'):
                lighting = run_lightmapper(False, paths.scenario.replace('/', '\\'), lightmap_quality=config['lighting'],
                                           cpu_threads=1, structure_bsps=['proof_box_bsp'])
                if lighting.lightmap_failed:
                    raise RuntimeError(lighting.lightmap_message)
            journal.finish(wait=True)
            sys.stdout.flush()
            evidence = lighting_evidence([p.read_text(encoding='utf-8', errors='replace')
                for p in {run/'blender-reach-worker.log', *(run/'tool-logs').glob('*.log')}])
            report['lighting_evidence'] = evidence
            if evidence['errors']:
                raise RuntimeError('Reach Faux log validation failed: '+evidence['errors'][0])
            report['lighting_status'] = 'REACH_FAUX_'+config['lighting'].upper()
        else:
            report['lighting_status'] = 'DIAGNOSTIC_SKIPPED'
        report['stage'] = 'native tag validation'
        flush()
        with profile.span('native Reach tag validation'):
            validate_native(paths, plan, run, report)
        report['status'] = 'COMPLETE'
    except Exception as exc:
        report.update(status='FAILED', failure=f"{report['stage']}: {exc}", traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        if journal:
            journal.finish(wait=True)
        if profile:
            report['profile'] = profile.report()
        flush()
    if report['status'] != 'COMPLETE':
        raise RuntimeError(report['failure'])


if __name__ == '__main__':
    main()

"""Run with the Python bundled in Blender; no installation or interactive UI.

python cli.py --h3-root ... --reach-root ... --blender ... --fixtures ... --work-dir ...
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import time
import traceback
import uuid

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = 'port_environment'

from . import BUILDER_VERSION, DEFAULT_NAMESPACE, FORMAT, SOURCE_SCENARIO
from . import fixtures
from .model import construct, stable_hash, used_shaders, plan_bsps, plan_skies
from .selection import select, SCENARIO_FIELDS
from . import evidence, dependencies
from .paths import OutputPaths, Ownership, atomic_json, build_lock, digest


class Commands:
    def __init__(self, directory, report):
        self.directory = directory
        self.report = report

    def run(self, name, command, cwd, env=None):
        log = self.directory / (name+'.log')
        row = dict(stage=name, command=[str(x) for x in command], cwd=str(cwd), log=str(log))
        self.report['tool_invocations'].append(row)
        started = time.perf_counter()
        print('Running '+name, flush=True)
        with log.open('xb') as stream:
            try:
                result = subprocess.run(row['command'], cwd=cwd, env=env, stdout=stream,
                                        stderr=subprocess.STDOUT, check=False)
                row['exit_code'] = result.returncode
            finally:
                row['seconds'] = time.perf_counter()-started
        if result.returncode:
            raise RuntimeError(f'{name} exited {result.returncode}; exact output: {log}')


def expected_tags(plan):
    scenario = plan['target']['scenario']
    return [scenario, *(b['destination'] for b in plan_bsps(plan)),
            *(b['destination'].rsplit('.',1)[0]+'.scenario_structure_lighting_info' for b in plan_bsps(plan)),
            *(s['destination'].rsplit('.',1)[0]+'.'+ext for s in plan_skies(plan) for ext in ('scenery','model','render_model')),
            *(d['destination'] for d in plan.get('structure_designs',[])),
            scenario.rsplit('.', 1)[0]+'_faux_lightmap.scenario_lightmap',
            *(m['destination'] for m in plan['materials'])]


def write_summary(directory, report):
    prefix = report.get('report_prefix','proof_box')
    atomic_json(directory/(prefix+'_build_report.json'), report)
    lines = [f"# H3 -> Reach environment {BUILDER_VERSION}", '', f"Build status: **{report['status']}**", '',
             f"Target: `{report['target_namespace']}`", '',
             'Runtime acceptance: **PENDING NATE**. Tool output is not proof of spawn, collision or visuals.', '',
             f"Lighting: {report.get('lighting_status', 'NOT_RUN')}", '',
             f"Build run: `{report['run_directory']}`", '']
    if report.get('selection'):
        selection = report['selection']
        lines += [f"Source zone: `{selection['source_zone_set']}`; authored BSP mask: `{selection['source_bsp_mask']}`.", '']
        for bsp in report.get('selected_bsp_sources', []):
            count = bsp['instances'].get('source_instance_count', 0)
            lines.append(f"- BSP {bsp['source_index']}: `{bsp['source_tag']}`; {count} BSP-owned placements")
        lines.append('')
    if report.get('failure'):
        lines += ['First failing boundary:', '', '```text', report['failure'], '```', '']
    if report.get('source_authenticity'):
        stats = report['source_authenticity']
        for name in ('render', 'collision', 'sky'):
            row = stats[name]
            lines.append(f"- H3 {name}: {row['vertices']} vertices, {row['triangles']} triangles; world bounds {row['bounds_world']}")
        lines.append('')
    lines += ['Files, hashes, classifications, commands, timings, mapping evidence, errors and worker validation are in the JSON report.', '',
              'Use the generated Tag Test snippet only after a GENERATED build. The compiler does not edit init.txt.', '']
    if report.get('unsupported'):
        from collections import Counter
        categories = Counter(r['reason'] for r in report['unsupported'])
        lines += [f"Unsupported source contracts: **{len(report['unsupported'])}**. JSON retains every source field, value and affected record.", '']
        lines += [f"- {count} contracts: {reason}" for reason,count in categories.items()]
    if report.get('source_dependencies'):
        dependency = report['source_dependencies']
        lines += ['', f"Dependency audit searched all **{dependency['inventory']['file_count']:,}** installed H3 files.", '']
        lines += [f"- {count}: {name}" for name,count in dependency['classification_counts'].items()]
        for binding in dependency['runtime_binding_overrides']:
            lines += ['', f"`{binding['source_shader']}` / `{binding['parameter']}`:",
                f"loose `{binding['original_bitmap']}` resolves through verified stock H3 cache evidence to",
                f"`{binding['authoring_bitmap']}`. The original snapshot is retained; authoring uses decoded H3 source pixels."]
        lines += ['', 'Per-surface/instance usage, exact-name searches and cache hashes are in `source-dependencies.json` in the run directory.',
                  f"Dependency audit: {report['source_dependency_audit_seconds']:.3f} seconds."]
    if report.get('lighting_inputs'):
        lines += ['', '| Lighting input/readback | Count or status |', '| --- | --- |']
        lines += [f'| {name} | {value} |' for name,value in report['lighting_inputs'].items()]
    if report.get('stage_timings'):
        lines += ['', '| Stage | Status | Seconds |', '| --- | --- | --- |']
        for name,row in report['stage_timings'].items():
            seconds = f"{row['seconds']:.3f}" if row['seconds'] is not None else 'not run'
            lines.append(f"| {name} | {row['status']} | {seconds} |")
    (directory/(prefix+'_build_report.md')).write_text('\n'.join(lines), encoding='utf-8')


def finish_stage_timings(report):
    """CLI and native Tool journals have different schemas; neither is optional evidence."""
    invocations = report['tool_invocations']
    for name, prefixes in [('H3 source decode', ('h3-scenario-decode', 'h3-xml-scenario')),
                           ('sky', ('h3-sky-', 'h3-xml-sky-'))]:
        rows = [r for r in invocations if r.get('stage', '').startswith(prefixes)]
        if rows:
            report['stage_timings'][name] = dict(status='SOURCE_EXTRACTED', seconds=sum(r['seconds'] for r in rows))
    helper = report.get('source_material_helper_timings', {})
    for name, key in [('materials', 'shader_metadata_exclusive_seconds'), ('bitmaps', 'bitmap_extraction_seconds')]:
        if key in helper:
            report['stage_timings'][name] = dict(status='SOURCE_EXTRACTED', seconds=helper[key])
    for name, prefixes in [('structure design', ('h3-xml-design-',)),
                           ('lighting', ('h3-xml-lighting-', 'h3-xml-light-tag-'))]:
        rows = [r for r in invocations if r.get('stage', '').startswith(prefixes)]
        if rows:
            report['stage_timings'][name] = dict(status='SOURCE_EXTRACTED', seconds=sum(r['seconds'] for r in rows))
    worker = report.get('worker', {})
    for name, faux in [('Tool', False), ('Faux', True)]:
        rows = [r for r in worker.get('tool_invocations', []) if len(r.get('command', [])) > 1
                and r['command'][1].startswith('faux') == faux]
        if rows:
            report['stage_timings'][name] = dict(
                status='PROCESS_EXIT_ZERO' if all(r.get('status') == 'ACCEPTED' for r in rows) else 'FAILED_OR_INCOMPLETE',
                seconds=sum(r.get('seconds', 0) for r in rows))
    readback = worker.get('lighting_input_readback')
    if readback:
        counts = report['lighting_inputs']
        for report_key, key in [('Reach_sky_samples_written', 'sky_samples'),
            ('Reach_light_definitions_written', 'light_definitions'), ('Reach_light_instances_written', 'light_instances'),
            ('Reach_emissive_rows_written', 'emissive_rows')]:
            counts[report_key] = readback['native'][key]
        counts['validation_status'] = readback['status']


def file_provenance(path, plan, worker):
    if not plan:
        return dict(source_paths=[], strategy='Partial output before a completed source plan', classification='UNRESOLVED')
    sources = [plan['source']['scenario'],*(b['source_tag'] for b in plan_bsps(plan))]
    strategy = 'Normal Foundry scenario/BSP export and Reach Tool regeneration'
    name = path.split('/',1)[1]
    for material in plan['materials']:
        if name == material['destination']:
            sources, strategy = [material['source_shader']], material['strategy']
    for bitmap in worker.get('bitmap_builds', []):
        destination = bitmap['destination'].replace('\\','/')
        if name.rsplit('.',1)[0] == destination.rsplit('.',1)[0]:
            source = bitmap['source_bitmap'].replace('\\','/')
            sources, strategy = [source+'.bitmap' if not source.endswith('.bitmap') else source], 'H3 decoded pixels -> Foundry export_bitmap -> Reach Tool'
    for sky in plan_skies(plan):
        if name.startswith(sky['destination'].rsplit('/',1)[0]+'/'):
            sources = [sky['source_scenery'],sky['source_model'],sky['source_render_model']]
            strategy = 'H3 source sky -> normal Foundry sky/model export -> Reach Tool'
    if 'lightmap' in name or name.endswith('.probestore'):
        sources += [plan['lighting']['source_tag'], *(s['source_render_model'] for s in plan_skies(plan))]
        strategy = 'Reach Faux regenerates lighting from H3-derived geometry and sky samples'
    return dict(source_paths=sources, strategy=strategy, classification='GENERATED',
                source_hashes={p:plan['source']['hashes'][p] for p in sources})


def cleanup_dependencies(run):
    target = run/'python-dependencies'
    if not target.exists():
        return
    checked = target.resolve(strict=True)
    if checked != target or not checked.is_relative_to(run.resolve()):
        raise ValueError('Dependency cleanup path is redirected')
    for path in [target, *target.rglob('*')]:
        if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):
            raise ValueError('Refusing redirected dependency cleanup')
    shutil.rmtree(checked)


def build(args):
    paths = OutputPaths(args.h3_root, args.reach_root, args.namespace,allow_nested=args.scenario.replace('\\','/')!=SOURCE_SCENARIO)
    ownership = Ownership(paths, args.work_dir)
    # Preflight is read-only. A new report directory must be empty, so report
    # filenames never overwrite unrelated user documents.
    if ownership.directory.exists() and not ownership.manifest.exists() and any(ownership.directory.iterdir()):
        raise ValueError('Work directory contains unowned files; choose a new empty directory')
    before = ownership.preflight()
    blender = Path(args.blender).resolve(strict=True)
    addon = Path(__file__).resolve().parents[2]
    helpers = Path(args.helpers).resolve(strict=True) if args.helpers else addon/'h3_import/bin'
    for tool in ('h3-scenario-inspect.exe', 'h3-object-bridge.exe', 'h3-shader-bridge.exe'):
        if not (helpers/tool).is_file():
            raise FileNotFoundError('Missing bundled source helper: '+str(helpers/tool))
    for tool in (paths.h3/'tool.exe', paths.reach/'tool.exe', paths.reach/'tool_fast.exe',
                 paths.reach/'bin/ManagedBlam.dll', paths.reach/'project.xml'):
        if not tool.is_file():
            raise FileNotFoundError(str(tool))
    source_scenario = args.scenario.replace('\\','/')
    paths.source(source_scenario)
    if source_scenario != SOURCE_SCENARIO and (paths.namespace == DEFAULT_NAMESPACE or paths.namespace.startswith(DEFAULT_NAMESPACE+'/')):
        raise ValueError('A campaign build cannot use the proof_box regression namespace')
    fixture_validation = fixtures.validate_archive(args.fixtures) if args.fixtures else None
    if source_scenario == SOURCE_SCENARIO and fixture_validation is None:
        raise ValueError('The proof_box regression requires --fixtures')
    lock_key = paths.fingerprint()+'-'+stable_hash(paths.namespace)[:16]
    # A single target lock, independent of report directory, also serializes the
    # existing Foundry Faux job id. No concurrent builds share its blob directory.
    with build_lock(Path(tempfile.gettempdir())/'foundry_h3_port_locks'/lock_key):
        before = ownership.preflight()
        ownership.directory.mkdir(parents=True, exist_ok=True)
        build_id = time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
        run = ownership.directory/'runs'/build_id
        run.mkdir(parents=True)
        report = dict(format=FORMAT+'.build-report', version=1, builder_version=BUILDER_VERSION,
                      build_id=build_id, status='BUILDING', target_namespace=paths.namespace,
                      run_directory=str(run), tool_invocations=[], warnings=[], failures=[],
                      loader_status='PENDING_NATE', runtime_success=False, engineering_success=False,
                      lighting_status='NOT_RUN', fixture_validation=fixture_validation,
                      report_prefix='proof_box' if source_scenario == SOURCE_SCENARIO else paths.asset,
                      source_scenario=source_scenario,source_zone_set=args.zone_set,
                      stage_timings={name:dict(status='NOT_RUN',seconds=None) for name in (
                          'H3 source decode','BSP construction','instance construction','materials','bitmaps','sky',
                          'structure design','lighting','GR2/sidecar','Tool','Faux','native validation')},
                      reused_infrastructure=['H3 scenario/object/shader helpers', 'ReachStager',
                          'Foundry ExportScene/Granny/SidecarImport', 'ScenarioTag',
                          'ShaderTag.write_tag', 'export_bitmap', 'export_lights', 'LightMapper'])
        commands = Commands(run, report)
        start = time.perf_counter()
        ownership.save('BUILDING', before, build_id)
        plan = None
        try:
            provenance_files = [blender, *(helpers/name for name in ('h3-scenario-inspect.exe',
                'h3-object-bridge.exe','h3-shader-bridge.exe')), paths.h3/'tool.exe', paths.reach/'tool.exe',
                paths.reach/'tool_fast.exe', paths.reach/'bin/ManagedBlam.dll', paths.reach/'project.xml']
            report['build_tools_and_project'] = {str(p):digest(p) for p in provenance_files}
            report['authoring_oracles']=evidence.archives(args)
            kit_sources = [paths.h3/'tags/shaders'/n for n in ('foliage_fx.hlsl_include',
                'alpha_test_fx.hlsl_include','terrain_fx.hlsl_include')]
            kit_sources += [paths.reach/'tags/shaders/templated'/n for n in ('foliage.hlsl_include',
                'alpha_test.hlsl_include','terrain.hlsl_include','terrain_new.hlsl_include')]
            report['semantic_kit_source_evidence'] = {str(p):digest(p) for p in kit_sources if p.is_file()}
            code = [*Path(__file__).parent.glob('*.py'), Path(__file__).with_name('mappings.json'),
                    Path(__file__).with_name('semantic_catalog.json'),
                    addon/'tools/scenario/lightmap.py', addon/'blender_manifest.toml']
            report['compiler_source_hashes'] = {p.relative_to(addon).as_posix():digest(p) for p in code}
            package = addon.parent/'build.json'
            if package.is_file():
                metadata = json.loads(package.read_text(encoding='utf-8'))
                report['package'] = {key:metadata[key] for key in ('source_commit','extension_sha256')}
            commands.run('blender-version', [blender,'--version'], addon)
            (run/'source').mkdir()
            (run/'sky').mkdir()
            (run/'materials').mkdir()
            commands.run('h3-xml-scenario',[paths.h3/'tool.exe','export-tag-to-xml',paths.source(source_scenario),run/'scenario.xml'],paths.h3)
            scenario_xml=fixtures.read_authoring(run/'scenario.xml',SCENARIO_FIELDS)
            selection=select(scenario_xml,source_scenario,args.zone_set,args.spawn_flag)
            report['selection']=selection
            atomic_json(run/'selection.plan.json',selection)
            selected_indices=','.join(str(r['source_index']) for r in selection['bsps'])
            commands.run('h3-scenario-decode', [helpers/'h3-scenario-inspect.exe', '--input', paths.source(source_scenario),
                         '--tags-root', paths.h3_tags, '--output', run/'source', '--geometry', '--bsp-indices', selected_indices,
                         '--environment-semantics', *(['--environment-only'] if source_scenario != SOURCE_SCENARIO else [])], helpers)
            scene = json.loads((run/'source/scene.h3scene.json').read_text(encoding='utf-8'))
            bsps=[];skies=[];lighting_xmls={};designs={};sky_xmls={};sky_render_xmls={};light_xmls={}
            def xml(name,tag):
                target=run/(name+'.xml')
                commands.run('h3-xml-'+name,[paths.h3/'tool.exe','export-tag-to-xml',paths.source(tag),target],paths.h3)
                return fixtures.parse(target.read_bytes())
            for row in selection['bsps']:
                entry=next(e for e in scene['bsp_entries'] if e['index']==row['source_index'])
                if entry['status']!='extracted': raise ValueError('Selected BSP extraction failed: '+json.dumps(entry))
                bsps.append(json.loads((run/'source'/entry['geometry']).read_text(encoding='utf-8')))
                lighting_xmls[row['lighting_info']]=xml('lighting-'+str(row['source_index']),row['lighting_info'])
                if row['structure_design'] and row['structure_design'] not in designs:
                    designs[row['structure_design']]=xml('design-'+str(row['source_index']),row['structure_design'])
            seams_xml=xml('seams',selection['structure_seams']) if selection['structure_seams'] else None
            seam_source_context = None
            if seams_xml is not None and selection['classification'] != 'TARGET_DEFAULT':
                from port_environment import seam_states
                def seam_metadata(source_index, tag):
                    target = run/f'seam-neighbor-{source_index}.xml'
                    commands.run('h3-xml-seam-neighbor-'+str(source_index),
                        [paths.h3/'tool.exe','export-tag-to-xml',paths.source(tag),target],paths.h3)
                    return fixtures.read_authoring(target, {'seam identifiers'}), dict(
                        source_sha256=digest(paths.source(tag)), xml=target.name, xml_sha256=digest(target))
                seam_source_context = seam_states.discover_neighbors(scenario_xml,bsps,seams_xml,seam_metadata)
                atomic_json(run/'source-seam-context.json',seam_source_context)
            for row in selection['light_palette']:
                source=row['source_tag']
                if source and source not in light_xmls:
                    light_xmls[source]=xml('light-tag-'+str(row['source_index']),source)
            for row in selection['skies']:
                name='sky-'+str(row['source_index']);directory=run/'sky'/name;directory.mkdir()
                commands.run('h3-'+name+'-decode',[helpers/'h3-object-bridge.exe','--input',paths.source(row['source_tag']),
                             '--tags-root',paths.h3_tags,'--output',directory],helpers)
                sky=json.loads((directory/'asset.h3asset.json').read_text(encoding='utf-8'));skies.append(sky)
                sky_xmls[row['source_tag']]=xml(name,row['source_tag'])
                sky_render_xmls[row['source_tag']]=xml(name+'-render',sky['dependencies']['render_model'])
            request = dict(scene, shader_paths=used_shaders(bsps,skies))
            atomic_json(run/'materials/request.json', request)
            commands.run('h3-material-decode', [helpers/'h3-shader-bridge.exe', '--asset', run/'materials/request.json',
                         '--tags-root', paths.h3_tags, '--reach-tags-root', paths.roots['tags'], '--output', run/'materials',
                         '--single-image-pixels'], helpers)
            shaders = json.loads((run/'materials/shader_manifest.json').read_text(encoding='utf-8'))
            authoring_manifest = 'shader_manifest.json'
            if selection['classification'] != 'TARGET_DEFAULT':
                dependency_started = time.perf_counter()
                inventory = dependencies.TagInventory(paths.h3_tags)
                atomic_json(run/'h3-tags.inventory.json', dict(inventory.summary, files=sorted(inventory.files)), compact=True)
                usage = dependencies.shader_usage(bsps, skies)
                atomic_json(run/'selected-shader-usage.json', usage, compact=True)
                cache_records = []
                cache_evidence = getattr(args, 'source_cache_evidence', None)
                if cache_evidence:
                    cache_records = json.loads(Path(cache_evidence).read_text(encoding='utf-8-sig'))
                    report['supplied_cache_evidence'] = dict(file=str(Path(cache_evidence).resolve()), sha256=digest(cache_evidence))
                cache_reader = getattr(args, 'source_cache_reader', None)
                cache_files = getattr(args, 'source_cache', None)
                request = dependencies.cache_request(shaders, inventory, usage=usage)
                if request['shaders'] and cache_reader and cache_files:
                    reader = Path(cache_reader).resolve(strict=True)
                    report['build_tools_and_project'][str(reader)] = digest(reader)
                    atomic_json(run/'cache-dependency-request.json', request)
                    try:
                        commands.run('h3-stock-cache-bindings', [reader, run/'cache-dependency-request.json', *cache_files], run)
                        cache_records.extend(json.loads((run/'h3-stock-cache-bindings.log').read_text(encoding='utf-8-sig')))
                    except (RuntimeError, json.JSONDecodeError) as exc:
                        # An unavailable reader does not prove a missing runtime
                        # dependency. Finish the usage audit and preserve the error.
                        report['source_cache_reader_failure'] = str(exc)
                        cache_records = []
                shaders, dependency_report = dependencies.audit(shaders, bsps, skies, selection, inventory, cache_records, usage=usage)
                authoring_manifest = 'authoring-shader-manifest.json'
                atomic_json(run/'materials'/authoring_manifest, shaders)
                atomic_json(run/'source-dependencies.json', dependency_report)
                report['source_dependencies'] = dependency_report
                report['source_dependency_audit_seconds'] = time.perf_counter()-dependency_started
            plan_started=time.perf_counter()
            if selection['classification']=='TARGET_DEFAULT':
                first=selection['bsps'][0];ss=selection['skies'][0]['source_tag']
                plan=construct(paths,scene,bsps[0],skies[0],shaders,scenario_xml,lighting_xmls[first['lighting_info']],
                               sky_xmls[ss],sky_render_xmls[ss],lighting_quality=args.lighting)
            else:
                plan=construct(paths,scene,bsps,skies,shaders,scenario_xml,lighting_xmls,sky_xmls,sky_render_xmls,
                               lighting_quality=args.lighting,selection=selection,designs=designs,seams_xml=seams_xml,
                               light_xmls=light_xmls,seam_source_context=seam_source_context)
            report['semantic_planning_seconds']=time.perf_counter()-plan_started
            if plan.get('source_semantic_resolution') is not None:
                from port_environment import semantics
                baseline_path = getattr(args, 'semantic_baseline', None)
                if baseline_path:
                    baseline = json.loads(Path(baseline_path).read_text(encoding='utf-8-sig'))
                    report['source_semantic_baseline'] = dict(file=str(Path(baseline_path).resolve()), sha256=digest(baseline_path))
                    semantics.reconcile_baseline(plan, baseline)
                plan['plan_sha256'] = stable_hash({k:v for k,v in plan.items() if k != 'plan_sha256'})
                resolution = plan['source_semantic_resolution']
                resolution['kit_source_evidence'] = report['semantic_kit_source_evidence']
                plan['plan_sha256'] = stable_hash({k:v for k,v in plan.items() if k != 'plan_sha256'})
                atomic_json(run/'source-semantic-resolution.json', resolution)
                atomic_json(run/'original-source-contracts.json', plan['source_contract_observations'])
                atomic_json(run/'semantic-mapping-catalog.json', semantics.CATALOG)
                (run/'source-semantic-resolution.md').write_text(semantics.markdown(resolution), encoding='utf-8')
                from port_environment import breakables
                breakable_report = breakables.report(resolution)
                atomic_json(run/'breakable-collision-report.json', breakable_report)
                (run/'breakable-collision-report.md').write_text(breakables.markdown(breakable_report), encoding='utf-8')
                report['breakable_collision_report'] = str(run/'breakable-collision-report.json')
                report['source_semantic_accounting'] = {k:v for k,v in resolution.items() if k != 'records'}
            plan_path = run/'environment.plan.json'
            atomic_json(plan_path, plan,compact=plan['version']>=2)
            report.update(plan=str(plan_path), plan_sha256=plan['plan_sha256'], source=plan['source'],
                          mappings_used=plan['mappings_used'], expected_tags=expected_tags(plan),
                          source_authenticity=dict(render=plan_bsps(plan)[0]['source_render'], collision=plan_bsps(plan)[0]['source_collision'],
                                                   sky=plan_skies(plan)[0]['source_geometry']),
                          source_helper_timings=dict(scenario=scene.get('bsp_entries'), materials=shaders.get('timings'),
                                                     material_cache=shaders.get('cache')),
                          remaining_unknowns=plan['unknowns'])
            report['target_defaults'] = dict(classification='TARGET_DEFAULT', scenario=plan['scenario']['defaults'],
                spawn=plan['scenario']['spawn'], zone_set=plan['scenario']['zone_set'], sky_index=0,
                sky_bounce=plan['lighting']['sky']['defaults'])
            report['target_defaults']['sky_model'] = plan_skies(plan)[0]['target_defaults']
            report['unsupported']=plan.get('unsupported',[])
            atomic_json(run/'unsupported-semantics.json',report['unsupported'])
            report['selected_bsp_sources']=[dict(source_tag=b['source_tag'],destination=b['destination'],
                source_index=b.get('source_index',0),base_render=b['source_render'],base_collision=b['source_collision'],
                instances={k:v for k,v in b.get('instance_plan',{}).items() if k not in {'placements','used_render_instances'}})
                for b in plan_bsps(plan)]
            report['lighting_inputs']={
                'source_sky_light_samples':sum(len(s.get('lighting',plan['lighting']['sky'])['source_samples']) for s in plan_skies(plan)),
                'source_generic_static_lights':sum(len(l['source_semantics']['light_instances']) for l in plan.get('lighting_by_bsp',[plan['lighting']])),
                'source_emissive_material_rows':sum(float(m['emissive power'])!=0 for l in plan.get('lighting_by_bsp',[plan['lighting']]) for m in l['source_semantics']['materials']),
                'Reach_sky_samples_written':0,'Reach_light_definitions_written':0,'Reach_light_instances_written':0,
                'Reach_emissive_rows_written':0,'validation_status':'NOT_RUN_SOURCE_GATE'}
            if report['unsupported']:
                atomic_json(run/'unsupported-semantics.json',report['unsupported'])
                raise ValueError(f"{len(report['unsupported'])} unsupported source contracts; native authoring refused. See {run/'unsupported-semantics.json'}")
            report['stock_replacements'] = []
            report['debug_fallbacks'] = []
            snippet = 'game_start '+paths.scenario.replace('/', '\\')+'\n'
            snippet_path=ownership.directory/(report['report_prefix']+'_init_snippet.txt')
            config = dict(plan=str(plan_path), source_directory=str(run/'materials'),
                          shader_manifest=authoring_manifest,
                          source_scenario=source_scenario,
                          h3_root=str(paths.h3), reach_root=str(paths.reach), namespace=paths.namespace,
                          run_directory=str(run), report_directory=str(ownership.directory),
                          plan_sha256=plan['plan_sha256'], lighting=args.lighting)
            atomic_json(run/'worker-config.json', config)
            if not args.plan_only:
                env = dict(os.environ, BLENDER_USER_CONFIG=str(run/'blender-config'),
                           BLENDER_USER_SCRIPTS=str(run/'blender-scripts'))
                commands.run('blender-reach-worker', [blender, '--background', '--factory-startup', '--python-exit-code', '1',
                             '--python', Path(__file__).with_name('worker.py'), '--', run/'worker-config.json'], addon, env)
                worker = json.loads((run/'worker-report.json').read_text(encoding='utf-8'))
                report['worker'] = worker
                if worker['status'] != 'COMPLETE':
                    raise RuntimeError('Worker did not report a completed native build')
                for tag in expected_tags(plan):
                    if args.lighting == 'none' and tag.endswith('.scenario_lightmap'):
                        continue
                    path = paths.destination('tags', tag[len(paths.namespace)+1:])
                    if not path.is_file() or path.stat().st_size == 0:
                        raise RuntimeError('Expected generated Reach tag missing: '+str(path))
                report['lighting_status'] = worker['lighting_status']
                report['engineering_success'] = True
                report['status'] = 'GENERATED' if args.lighting != 'none' else 'GEOMETRY_DIAGNOSTIC_ONLY'
                snippet_path.write_text(snippet,encoding='ascii')
            else:
                report['status'] = 'PLANNED'
        except Exception as exc:
            report['status'] = 'FAILED'
            report['failure'] = str(exc)
            report['failures'].append(dict(message=str(exc), traceback=traceback.format_exc()))
            print(report['failure'], file=sys.stderr, flush=True)
        finally:
            worker_report = run/'worker-report.json'
            if worker_report.exists():
                worker = json.loads(worker_report.read_text(encoding='utf-8'))
                report['worker'] = worker
                report['tool_invocations'].extend(worker.get('tool_invocations', []))
                report['lighting_status'] = worker.get('lighting_status', 'NOT_RUN')
                if worker.get('failure'):
                    report['first_authoritative_failure'] = worker['failure']
            after = paths.snapshot()
            report['generated_files'] = [dict(path=p, sha256=sha, previous_sha256=before.get(p),
                                            builder_version=BUILDER_VERSION,
                                            **file_provenance(p,plan,report.get('worker',{})),
                                            source_plan_sha256=report.get('plan_sha256'))
                                       for p, sha in sorted(after.items())]
            report['seconds'] = time.perf_counter()-start
            if 'shaders' in locals():
                report['source_material_helper_timings']=shaders.get('timings',{})
            finish_stage_timings(report)
            if report.get('unsupported'):
                report['status']='BLOCKED_SOURCE_SEMANTICS'
            try:
                cleanup_dependencies(run)
                report['disposable_dependency_cleanup'] = 'COMPLETE'
            except Exception as exc:
                report['warnings'].append('Disposable dependency cleanup failed: '+str(exc))
            ownership.save(report['status'], after, build_id)
            write_summary(run, report)
            write_summary(ownership.directory, report)
        print(f"{report['status']}: {ownership.directory/(report['report_prefix']+'_build_report.md')}", flush=True)
        if report['status']=='GENERATED':
            print('Tag Test command: game_start '+paths.scenario.replace('/', '\\'), flush=True)
        return 0 if report['status'] in {'GENERATED','PLANNED','GEOMETRY_DIAGNOSTIC_ONLY'} else 1


def main():
    parser = argparse.ArgumentParser(description='Compile a selected H3 scenario zone set through normal Reach Foundry')
    parser.add_argument('--h3-root', required=True)
    parser.add_argument('--reach-root', required=True)
    parser.add_argument('--blender', required=True)
    parser.add_argument('--fixtures', help='Required for proof_box: paired H3_Reach_Box_Fixtures.zip')
    parser.add_argument('--scenario',default=SOURCE_SCENARIO)
    parser.add_argument('--zone-set',help='Exact authored source zone-set name')
    parser.add_argument('--spawn-flag',help='Exact source cutscene flag used as the player start')
    parser.add_argument('--h3-xml-evidence',help='Optional user-supplied H3TagXML.zip authoring oracle')
    parser.add_argument('--reach-xml-evidence',help='Optional user-supplied ReachTagXML.zip authoring oracle')
    parser.add_argument('--templates',help='Optional HREK templates.zip authoring oracle')
    parser.add_argument('--source-cache-evidence', help='Read-only H3 stock cache sampler evidence JSON; cache hashes are rechecked')
    parser.add_argument('--source-cache-reader', help='Optional H3CacheEvidence executable; emits metadata only')
    parser.add_argument('--source-cache', action='append', help='Stock H3 .map file for dependency classification; repeatable')
    parser.add_argument('--work-dir', required=True, help='New empty directory outside both kits, or the same owned build directory')
    parser.add_argument('--namespace', default=DEFAULT_NAMESPACE)
    parser.add_argument('--helpers', help='Override directory containing the bundled source helper executables')
    parser.add_argument('--lighting', choices=('direct_only', 'draft', 'none'), default='direct_only')
    parser.add_argument('--plan-only', action='store_true')
    parser.add_argument('--semantic-baseline', help='Original unsupported-semantics.json to reconcile by stable source-record identity')
    args = parser.parse_args()
    try:
        return build(args)
    except Exception as exc:
        print(f'Preflight rejected: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

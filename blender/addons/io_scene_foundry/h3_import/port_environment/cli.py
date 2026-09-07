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
from .model import construct, stable_hash
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
    ns = plan['target']['namespace']
    scenario = plan['target']['scenario']
    sky = plan['sky']['destination'].rsplit('.', 1)[0]
    return [scenario, plan['bsp']['destination'],
            plan['bsp']['destination'].rsplit('.', 1)[0]+'.scenario_structure_lighting_info',
            sky+'.scenery', sky+'.model', sky+'.render_model',
            scenario.rsplit('.', 1)[0]+'_faux_lightmap.scenario_lightmap',
            *(m['destination'] for m in plan['materials'])]


def write_summary(directory, report):
    atomic_json(directory/'proof_box_build_report.json', report)
    lines = [f"# H3 -> Reach proof_box {BUILDER_VERSION}", '', f"Build status: **{report['status']}**", '',
             f"Target: `{report['target_namespace']}`", '',
             'Runtime acceptance: **PENDING NATE**. Tool output is not proof of spawn, collision or visuals.', '',
             f"Lighting: {report.get('lighting_status', 'NOT_RUN')}", '',
             f"Build run: `{report['run_directory']}`", '']
    if report.get('failure'):
        lines += ['First failing boundary:', '', '```text', report['failure'], '```', '']
    if report.get('source_authenticity'):
        stats = report['source_authenticity']
        for name in ('render', 'collision', 'sky'):
            row = stats[name]
            lines.append(f"- H3 {name}: {row['vertices']} vertices, {row['triangles']} triangles; world bounds {row['bounds_world']}")
        lines.append('')
    lines += ['Files, hashes, classifications, commands, timings, mapping evidence, errors and worker validation are in the JSON report.', '',
              'Tag Test: append the generated `proof_box_init_snippet.txt` command to your own init file, or enter it in the Tag Test console. The compiler does not edit init.txt.', '']
    (directory/'proof_box_build_report.md').write_text('\n'.join(lines), encoding='utf-8')


def file_provenance(path, plan, worker):
    if not plan:
        return dict(source_paths=[], strategy='Partial output before a completed source plan', classification='UNRESOLVED')
    sources = [plan['source']['scenario'],plan['bsp']['source_tag']]
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
    if '/sky/proof_box_sky/' in name:
        sources = [plan['sky']['source_scenery'],plan['sky']['source_model'],plan['sky']['source_render_model']]
        strategy = 'H3 source sky -> normal Foundry sky/model export -> Reach Tool'
    if 'lightmap' in name or name.endswith('.probestore'):
        sources += [plan['lighting']['source_tag'], plan['sky']['source_render_model']]
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
    paths = OutputPaths(args.h3_root, args.reach_root, args.namespace)
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
    paths.source(SOURCE_SCENARIO)
    fixture_validation = fixtures.validate_archive(args.fixtures)
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
            code = [*Path(__file__).parent.glob('*.py'), Path(__file__).with_name('mappings.json'),
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
            commands.run('h3-scenario-decode', [helpers/'h3-scenario-inspect.exe', '--input', paths.source(SOURCE_SCENARIO),
                         '--tags-root', paths.h3_tags, '--output', run/'source', '--geometry', '--bsp-indices', '0',
                         '--environment-semantics'], helpers)
            scene = json.loads((run/'source/scene.h3scene.json').read_text(encoding='utf-8'))
            bsp = json.loads((run/'source/geometry/bsp_0000.json').read_text(encoding='utf-8'))
            xmls = {}
            # The supplied XML is an oracle; authored values come from these live
            # source tags, whose hashes are in the final plan.
            for name, tag in [('scenario', SOURCE_SCENARIO),
                              ('lighting', 'levels/test/box/box.scenario_structure_lighting_info'),
                              ('sky', 'levels/test/box/sky/sky.scenery'),
                              ('sky_render', 'levels/test/box/sky/sky.render_model')]:
                target = run/(name+'.xml')
                commands.run('h3-xml-'+name, [paths.h3/'tool.exe', 'export-tag-to-xml', paths.source(tag), target], paths.h3)
                xmls[name] = fixtures.parse(target.read_bytes())
            source_sky = fixtures.reference(fixtures.block(xmls['scenario'], 'skies')[0], 'sky', 'scenery')
            commands.run('h3-sky-decode', [helpers/'h3-object-bridge.exe', '--input', paths.source(source_sky),
                         '--tags-root', paths.h3_tags, '--output', run/'sky'], helpers)
            sky = json.loads((run/'sky/asset.h3asset.json').read_text(encoding='utf-8'))
            request = dict(scene, shader_paths=sorted(set(scene['shader_paths']+sky['shader_paths'])))
            atomic_json(run/'materials/request.json', request)
            commands.run('h3-material-decode', [helpers/'h3-shader-bridge.exe', '--asset', run/'materials/request.json',
                         '--tags-root', paths.h3_tags, '--reach-tags-root', paths.roots['tags'], '--output', run/'materials',
                         '--single-image-pixels'], helpers)
            shaders = json.loads((run/'materials/shader_manifest.json').read_text(encoding='utf-8'))
            plan = construct(paths, scene, bsp, sky, shaders, xmls['scenario'], xmls['lighting'], xmls['sky'],
                             xmls['sky_render'], lighting_quality=args.lighting)
            plan_path = run/'environment.plan.json'
            atomic_json(plan_path, plan)
            report.update(plan=str(plan_path), plan_sha256=plan['plan_sha256'], source=plan['source'],
                          mappings_used=plan['mappings_used'], expected_tags=expected_tags(plan),
                          source_authenticity=dict(render=plan['bsp']['source_render'], collision=plan['bsp']['source_collision'],
                                                   sky=plan['sky']['source_geometry']),
                          source_helper_timings=dict(scenario=scene.get('bsp_entries'), materials=shaders.get('timings'),
                                                     material_cache=shaders.get('cache')),
                          remaining_unknowns=plan['unknowns'])
            report['target_defaults'] = dict(classification='TARGET_DEFAULT', scenario=plan['scenario']['defaults'],
                spawn=plan['scenario']['spawn'], zone_set=plan['scenario']['zone_set'], sky_index=0,
                sky_bounce=plan['lighting']['sky']['defaults'])
            report['target_defaults']['sky_model'] = plan['sky']['target_defaults']
            report['stock_replacements'] = []
            report['debug_fallbacks'] = []
            snippet = 'game_start '+paths.scenario.replace('/', '\\')+'\n'
            (ownership.directory/'proof_box_init_snippet.txt').write_text(snippet, encoding='ascii')
            config = dict(plan=str(plan_path), source_directory=str(run/'materials'),
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
            try:
                cleanup_dependencies(run)
                report['disposable_dependency_cleanup'] = 'COMPLETE'
            except Exception as exc:
                report['warnings'].append('Disposable dependency cleanup failed: '+str(exc))
            ownership.save(report['status'], after, build_id)
            write_summary(run, report)
            write_summary(ownership.directory, report)
        print(f"{report['status']}: {ownership.directory/'proof_box_build_report.md'}", flush=True)
        print('Tag Test command: game_start '+paths.scenario.replace('/', '\\'), flush=True)
        return 1 if report['status'] == 'FAILED' else 0


def main():
    parser = argparse.ArgumentParser(description='Compile only H3 test/box through normal Reach Foundry')
    parser.add_argument('--h3-root', required=True)
    parser.add_argument('--reach-root', required=True)
    parser.add_argument('--blender', required=True)
    parser.add_argument('--fixtures', required=True, help='Paired H3_Reach_Box_Fixtures.zip (semantic evidence only)')
    parser.add_argument('--work-dir', required=True, help='New empty directory outside both kits, or the same owned build directory')
    parser.add_argument('--namespace', default=DEFAULT_NAMESPACE)
    parser.add_argument('--helpers', help='Override directory containing the bundled source helper executables')
    parser.add_argument('--lighting', choices=('direct_only', 'draft', 'none'), default='direct_only')
    parser.add_argument('--plan-only', action='store_true')
    args = parser.parse_args()
    try:
        return build(args)
    except Exception as exc:
        print(f'Preflight rejected: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

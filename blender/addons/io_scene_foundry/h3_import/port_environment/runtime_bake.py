"""Bake an owned, existing environment without reconstructing geometry or lights.

The explicit parent manifest must match every current output. Preserve all tags
before invoking normal Foundry Faux, then validate source relationships again.
Run inside background Blender with a JSON config after --.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback
from types import SimpleNamespace


def require_parent(actual, owned, preserved):
    """Hash-pinned external additions are read-only, never adopted as outputs."""
    if set(owned) & set(preserved):
        raise ValueError('External preservation cannot override an owned output')
    if actual != {**owned, **preserved}:
        raise ValueError('Current outputs differ from the parent manifest and preserved additions')


def main(config):
    addon = Path(config['addon']).resolve()
    sys.path[:0] = [str(addon.parent), str(addon/'h3_import')]
    from port_environment import snapshot, worker, native_world
    from port_environment.paths import OutputPaths, Ownership, digest, atomic_json, build_lock
    from port_environment.validation import lighting_evidence
    quality = config.get('quality', 'low')
    if quality not in {'low', 'direct_only'}:
        raise ValueError('This comparison supports low or direct_only')
    run = Path(config['run']).resolve()
    paths = OutputPaths(config['h3_root'], config['reach_root'], config['namespace'], allow_nested=True)
    ownership = Ownership(paths, run)  # Reject report directories inside either kit.
    if run.exists():
        raise ValueError('Use a new bake comparison directory')
    parent = json.loads(Path(config['parent_manifest']).read_text())
    if (parent['namespace'] != paths.namespace or parent['project_fingerprint'] != paths.fingerprint()
            or parent['status'] != 'GENERATED'):
        raise ValueError('Expected a completed ownership manifest for this target')
    before = paths.snapshot()
    preserved = config.get('preserved_external_files', {})
    require_parent(before, parent['files'], preserved)
    plan, _, receipt = snapshot.load(config['accepted_plan'], paths, config['scenario'], config['zone_set'])
    run.mkdir(parents=True)
    report = dict(format='foundry.h3-environment.runtime-bake', version=1, status='PRESERVING',
        quality=quality, parent_manifest=str(config['parent_manifest']), before=before,
        source_snapshot=receipt, runtime_status='PENDING_NATE', tool_invocations=[],
        geometry_reconstructed=False, lighting_converter_changed=False,
        preserved_external_files=preserved)
    def flush():
        atomic_json(run/'runtime-bake-report.json', report)
    flush()
    for key, sha in before.items():
        if not key.startswith('tags/') and key not in preserved:
            continue
        target = run/'before'/key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(paths.reach/key, target)
        if digest(target) != sha:
            raise ValueError('Backup hash mismatch: '+key)
    ownership.save('PRESERVED', parent['files'], run.name)
    # require_parent performs the full preflight including explicitly preserved
    # external files. Keep those additions out of compiler ownership manifests.
    require_parent(paths.snapshot(), parent['files'], preserved)
    worker.dependencies(addon, run)
    import bpy
    bpy.ops.preferences.addon_enable(module='io_scene_foundry')
    from io_scene_foundry import utils, managed_blam
    from io_scene_foundry.managed_blam import Tag
    from io_scene_foundry.tools.scenario.lightmap import run_lightmapper, calc_job_id
    utils.module = SimpleNamespace(bl_info={'version': (1, 9, 49)})
    prefs = utils.get_prefs(); prefs.projects.clear(); project = prefs.projects.add()
    project.name = 'Owned environment bake comparison'
    project.project_path = str(paths.reach); project.project_xml = str(paths.reach/'project.xml')
    project.tags_directory = str(paths.roots['tags']); project.data_directory = str(paths.roots['data'])
    project.corinth = False
    worker.setup_scene(paths.asset, 'scenario', paths.scenario+'.sidecar.xml', 'default', project.name)
    os.chdir(paths.reach); managed_blam.mb_init(); worker.protect_tag_writes(paths, read_only=True)
    # Record the actual installed preset, not guessed quality settings.
    with Tag(path='globals/lightmapper_globals.lightmapper_globals', tag_must_exist=True) as tag:
        presets = tag.tag.SelectField('Block:quality settings').Elements
        matches = [e for e in presets if e.SelectField('name').GetStringData() == quality]
        if len(matches) != 1:
            raise ValueError('Installed Reach preset is absent or ambiguous')
        report['preset'] = {str(f.DisplayName): f.Data for f in matches[0].Fields if hasattr(f, 'Data')}
    report['preset_source_sha256'] = digest(paths.reach/'tags/globals/lightmapper_globals.lightmapper_globals')
    blob = paths.reach/'faux'/str(calc_job_id(paths.scenario.replace('/', '\\'), 'all'))
    if (blob/'logs').exists():
        shutil.copytree(blob/'logs', run/'previous-faux-logs')
    journal = worker.ToolJournal(paths, run, report, flush, lighting_qualities=(quality,))
    base_check = journal.check
    def check(command):
        command = base_check(command)
        if not command[1].startswith('faux') and command[1] != 'export-tag-to-xml':
            raise ValueError('Bake comparison cannot import or rebuild assets')
        return command
    journal.check = check
    start = time.perf_counter()
    with build_lock(run):
        try:
            worker.validate_lighting_inputs(plan, report)
            native_world.validate(plan, report)
            report['world_before'] = report.pop('native_world_readback')
            ownership.save('BUILDING', parent['files'], run.name)
            report['status'] = 'BAKING'; flush()
            result = run_lightmapper(False, paths.scenario.replace('/', '\\'), lightmap_quality=quality,
                cpu_threads=int(config.get('threads', 1)), structure_bsps=[b['region'] for b in plan['bsps']])
            journal.finish(wait=True)
            if result.lightmap_failed:
                raise RuntimeError(result.lightmap_message)
            if any(r.get('exit_code') != 0 for r in report['tool_invocations']):
                raise RuntimeError('Faux process failed')
            logs = [p.read_text(encoding='utf-8', errors='replace') for p in (run/'tool-logs').glob('*.log')]
            report['lighting_evidence'] = lighting_evidence(logs)
            if report['lighting_evidence']['errors']:
                raise RuntimeError('Faux log validation failed: '+str(report['lighting_evidence']['errors']))
            worker.validate_lighting_inputs(plan, report)
            native_world.validate(plan, report)
            after = paths.snapshot()
            if any(after.get(k) != sha for k, sha in preserved.items()):
                raise ValueError('A preserved external file changed during the bake')
            changed = {k: dict(before=before.get(k), after=after.get(k))
                for k in sorted(before.keys() | after.keys()) if before.get(k) != after.get(k)}
            allowed_extensions = {'.scenario', '.scenario_structure_bsp', '.scenario_lightmap',
                '.scenario_lightmap_bsp_data', '.scenario_faux_data', '.probestore', '.bitmap'}
            if any(not k.startswith('tags/'+paths.namespace+'/') or Path(k).suffix not in allowed_extensions
                    or (Path(k).suffix == '.bitmap' and not ('lightmap' in k or '/faux/' in k)) for k in changed):
                raise ValueError('Faux changed a non-lighting resource; inspect the preserved backup')
            report.update(status='GENERATED_PENDING_RUNTIME', after=after, changed_files=changed,
                seconds=time.perf_counter()-start, unchanged_outputs=len(before)-sum(k in before for k in changed))
            ownership.save('GENERATED', {k: v for k, v in after.items() if k not in preserved}, run.name)
        except Exception as exc:
            report.update(status='FAILED', failure=str(exc), traceback=traceback.format_exc(),
                seconds=time.perf_counter()-start, after=paths.snapshot())
            raise
        finally:
            journal.finish(wait=True)
            if (blob/'logs').exists():
                shutil.copytree(blob/'logs', run/'faux-logs')
            flush()
    print('BAKE_COMPARISON_COMPLETE', run)


if __name__ == '__main__':
    main(json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf-8-sig')))

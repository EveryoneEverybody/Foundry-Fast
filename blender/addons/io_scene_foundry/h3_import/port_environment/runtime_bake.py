"""Bake an owned, existing environment without reconstructing geometry or lights.

The explicit parent manifest must match every current output. Preserve all tags
before invoking normal Foundry Faux, then validate source relationships again.
Run inside background Blender with a JSON config after --.
"""
import json
import math
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


def intensity_view(plan, source_bsp_index, factor):
    """Ephemeral diagnostic override; the accepted source plan stays immutable."""
    if not math.isfinite(factor) or not 1 < factor <= 100:
        raise ValueError('Diagnostic scale must be finite, greater than 1 and at most 100')
    matches = [i for i, b in enumerate(plan['bsps']) if b['source_index'] == source_bsp_index]
    if len(matches) != 1:
        raise ValueError('Diagnostic BSP must identify one accepted source BSP')
    index = matches[0]
    light = plan['lighting_by_bsp'][index]
    if not light['definitions'] or not light['instances']:
        raise ValueError('Diagnostic requires existing authored lights')
    definitions = [dict(d, intensity=d['intensity']*factor) for d in light['definitions']]
    if any(not math.isfinite(d['intensity']) or d['intensity'] <= 0 for d in definitions):
        raise ValueError('Diagnostic requires finite positive source power')
    view = dict(plan, lighting_by_bsp=list(plan['lighting_by_bsp']))
    view['lighting_by_bsp'][index] = dict(light, definitions=definitions)
    return view, index


def main(config):
    addon = Path(config['addon']).resolve()
    sys.path[:0] = [str(addon.parent), str(addon/'h3_import')]
    from port_environment import snapshot, worker, native_world, fixtures, lighting_audit, emissive_diagnostic, sun_diagnostic
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
    material_diagnostic = config.get('material_power_diagnostic')
    sun_control = config.get('sun_diagnostic')
    if sum(bool(config.get(k)) for k in ('material_power_diagnostic', 'intensity_diagnostic', 'sun_diagnostic')) > 1:
        raise ValueError('Change only one semantic class per diagnostic')
    diagnostic = config.get('intensity_diagnostic') or material_diagnostic or sun_control
    diagnostic_index = None
    diagnostic_path = None
    comparison_plan = plan
    lighting_bsp = 'all'
    if diagnostic:
        audit_path = Path(diagnostic['audit_report'])
        audit = json.loads(audit_path.read_text())
        if (digest(audit_path) != diagnostic['audit_sha256'] or
                audit['static_lights']['status'] != 'STRUCTURAL_MATCH' or
                audit['provenance']['accepted_plan_sha256'] != digest(config['accepted_plan'])):
            raise ValueError('Diagnostic requires a pinned passing source/authored/native audit')
        if sun_control:
            comparison_plan, diagnostic_path, sun_values = sun_diagnostic.sun_view(
                plan, diagnostic['sky_index'], float(diagnostic['factor']))
        elif material_diagnostic:
            baseline_report = json.loads(Path(diagnostic['baseline_report']).read_text())
            comparison_plan, diagnostic_index, material_indices, material_bindings = emissive_diagnostic.material_power_view(
                plan, diagnostic['source_bsp_index'], diagnostic['source_material_slots'], float(diagnostic['power']),
                baseline_report['lighting_field_readback'])
        else:
            comparison_plan, diagnostic_index = intensity_view(plan, diagnostic['source_bsp_index'], float(diagnostic['factor']))
        if not sun_control and audit['provenance']['config']['bsp_index'] != diagnostic_index:
            raise ValueError('Audit describes a different BSP')
        if not sun_control:
            bsp = plan['bsps'][diagnostic_index]
            diagnostic_path = bsp['destination'].rsplit('.', 1)[0]+'.scenario_structure_lighting_info'
        if digest(paths.owned_tag(diagnostic_path)) != diagnostic['native_tag_sha256']:
            raise ValueError('Audited native lighting changed')
        baseline_xml = Path(audit['provenance']['config']['native_lighting_xml'])
        if digest(baseline_xml) != audit['provenance']['native_lighting_xml_sha256']:
            raise ValueError('Audited native XML changed')
        baseline_lighting = fixtures.lighting_semantics(fixtures.parse(baseline_xml.read_bytes()))
        parent_report_path = Path(diagnostic['baseline_report'])
        baseline_report = json.loads(parent_report_path.read_text())
        if (digest(parent_report_path) != diagnostic['baseline_report_sha256'] or
                baseline_report['quality'] != quality or baseline_report['after'] != before or
                baseline_report.get('lighting_bsp', 'all') != 'all'):
            raise ValueError('Diagnostic baseline quality, scope or outputs differ')
        merge = [r['command'] for r in baseline_report['tool_invocations'] if r['command'][1] == 'faux_farm_dillum_merge']
        if len(merge) != 1 or int(merge[0][3]) != int(config.get('threads', 1)):
            raise ValueError('Diagnostic worker count differs from baseline')
        # Match the parent all-BSP low bake. Changing BSP scope also changes
        # photon allocation/transport and would confound an intensity-only test.
    run.mkdir(parents=True)
    report = dict(format='foundry.h3-environment.runtime-bake', version=1, status='PRESERVING',
        quality=quality, parent_manifest=str(config['parent_manifest']), before=before,
        source_snapshot=receipt, runtime_status='PENDING_NATE', tool_invocations=[],
        geometry_reconstructed=False, lighting_converter_changed=False,
        preserved_external_files=preserved)
    report['intensity_diagnostic'] = config.get('intensity_diagnostic')
    report['material_power_diagnostic'] = material_diagnostic
    report['sun_diagnostic'] = sun_control
    report['lighting_bsp'] = lighting_bsp
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
    os.chdir(paths.reach); managed_blam.mb_init()
    worker.protect_tag_writes(paths, read_only=not bool(diagnostic))
    # Record the actual installed preset, not guessed quality settings.
    with Tag(path='globals/lightmapper_globals.lightmapper_globals', tag_must_exist=True) as tag:
        presets = tag.tag.SelectField('Block:quality settings').Elements
        matches = [e for e in presets if e.SelectField('name').GetStringData() == quality]
        if len(matches) != 1:
            raise ValueError('Installed Reach preset is absent or ambiguous')
        report['preset'] = {str(f.DisplayName): f.Data for f in matches[0].Fields if hasattr(f, 'Data')}
    report['preset_source_sha256'] = digest(paths.reach/'tags/globals/lightmapper_globals.lightmapper_globals')
    if diagnostic and report['preset_source_sha256'] != baseline_report['preset_source_sha256']:
        raise ValueError('Diagnostic lightmapper preset changed')
    blob = paths.reach/'faux'/str(calc_job_id(paths.scenario.replace('/', '\\'), lighting_bsp))
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
            if diagnostic:
                # The only authored mutation: the selected native power field.
                # Do not rebuild rows, change presets, or alter source recipes.
                if sun_control:
                    baseline_xml = run/'baseline-sky.xml'
                    utils.run_tool(['export-tag-to-xml', str(paths.owned_tag(diagnostic_path)), str(baseline_xml)], force_tool_fast=True)
                    journal.finish(wait=True)
                with Tag(path=diagnostic_path, tag_must_exist=True) as tag:
                    if Path(str(tag.tag_path.Filename)).resolve() != paths.owned_tag(diagnostic_path):
                        raise ValueError('Diagnostic tag resolved to another project')
                    if sun_control:
                        sun = tag.tag.SelectField('Array:sun').Elements
                        if sun.Count != 6:
                            raise ValueError('Unexpected native analytic sun array')
                        for index, value in enumerate(sun_values, start=3):
                            sun[index].Fields[0].Data = value
                    elif material_diagnostic:
                        materials = tag.tag.SelectField('Block:material info').Elements
                        for index in material_indices:
                            materials[index].SelectField('emissive power').Data = float(diagnostic['power'])
                    else:
                        definitions = tag.tag.SelectField('Block:generic light definitions').Elements
                        expected = comparison_plan['lighting_by_bsp'][diagnostic_index]['definitions']
                        if definitions.Count != len(expected):
                            raise ValueError('Diagnostic definition count changed')
                        for e, d in zip(definitions, expected):
                            e.SelectField('intensity').Data = d['intensity']
                    tag.tag_has_changes = True
                if sun_control:
                    report['sun_control_values'] = sun_values
                elif material_diagnostic:
                    report['diagnostic_material_bindings'] = material_bindings
                    report['authoring_equivalence'] = 'Existing Tool-compiled material info.emissive power; no geometry reimport or generic-light edit'
                else:
                    report['diagnostic_definition_powers'] = [dict(index=i, source=d['intensity'], diagnostic=expected[i]['intensity'])
                        for i, d in enumerate(plan['lighting_by_bsp'][diagnostic_index]['definitions'])]
                report['diagnostic_mutated_tag'] = diagnostic_path
                report['diagnostic_is_converter_fix'] = False
            if diagnostic:
                worker.protect_tag_writes(paths, read_only=True)
            worker.validate_lighting_inputs(comparison_plan, report)
            if diagnostic:
                native_xml = run/'diagnostic-lighting-before-faux.xml'
                utils.run_tool(['export-tag-to-xml', str(paths.owned_tag(diagnostic_path)), str(native_xml)], force_tool_fast=True)
                journal.finish(wait=True)
                if sun_control:
                    report['sun_only_readback'] = sun_diagnostic.assert_sun_delta(
                        baseline_xml.read_bytes(), native_xml.read_bytes(), float(diagnostic['factor']))
                    report['sun_only_readback'].update(native_xml=str(native_xml), sha256=digest(native_xml))
                    native_world.validate(comparison_plan, report)
                elif material_diagnostic:
                    report['material_power_only_readback'] = emissive_diagnostic.assert_material_power_delta(
                        baseline_xml.read_bytes(), native_xml.read_bytes(), material_indices, float(diagnostic['power']))
                    report['material_power_only_readback'].update(native_xml=str(native_xml), sha256=digest(native_xml))
                else:
                    actual = fixtures.lighting_semantics(fixtures.parse(native_xml.read_bytes()))
                    lighting_audit.assert_intensity_delta(baseline_lighting, actual, float(diagnostic['factor']))
                    report['intensity_only_readback'] = dict(status='VERIFIED_BEFORE_FAUX', native_xml=str(native_xml), sha256=digest(native_xml))
            ownership.save('BUILDING', parent['files'], run.name)
            report['status'] = 'BAKING'; flush()
            result = run_lightmapper(False, paths.scenario.replace('/', '\\'), lightmap_quality=quality,
                cpu_threads=int(config.get('threads', 1)), structure_bsps=[b['region'] for b in plan['bsps']],
                lightmap_all_bsps=lighting_bsp == 'all', lightmap_specific_bsp=lighting_bsp)
            journal.finish(wait=True)
            if result.lightmap_failed:
                raise RuntimeError(result.lightmap_message)
            if any(r.get('exit_code') != 0 for r in report['tool_invocations']):
                raise RuntimeError('Faux process failed')
            logs = [p.read_text(encoding='utf-8', errors='replace') for p in (run/'tool-logs').glob('*.log')]
            report['lighting_evidence'] = lighting_evidence(logs)
            if report['lighting_evidence']['errors']:
                raise RuntimeError('Faux log validation failed: '+str(report['lighting_evidence']['errors']))
            worker.validate_lighting_inputs(comparison_plan, report)
            if material_diagnostic or sun_control:
                native_xml = run/'diagnostic-lighting-after-faux.xml'
                utils.run_tool(['export-tag-to-xml', str(paths.owned_tag(diagnostic_path)), str(native_xml)], force_tool_fast=True)
                journal.finish(wait=True)
                if sun_control:
                    report['sun_after_faux'] = sun_diagnostic.assert_sun_delta(
                        baseline_xml.read_bytes(), native_xml.read_bytes(), float(diagnostic['factor']))
                else:
                    report['material_power_after_faux'] = emissive_diagnostic.assert_material_power_delta(
                        baseline_xml.read_bytes(), native_xml.read_bytes(), material_indices, float(diagnostic['power']))
            native_world.validate(comparison_plan if sun_control else plan, report)
            after = paths.snapshot()
            if any(after.get(k) != sha for k, sha in preserved.items()):
                raise ValueError('A preserved external file changed during the bake')
            changed = {k: dict(before=before.get(k), after=after.get(k))
                for k in sorted(before.keys() | after.keys()) if before.get(k) != after.get(k)}
            allowed_extensions = {'.scenario', '.scenario_structure_bsp', '.scenario_lightmap',
                '.scenario_lightmap_bsp_data', '.scenario_faux_data', '.probestore', '.bitmap'}
            if any(not k.startswith('tags/'+paths.namespace+'/') or
                    (Path(k).suffix not in allowed_extensions and k != 'tags/'+str(diagnostic_path))
                    or (Path(k).suffix == '.bitmap' and not ('lightmap' in k or '/faux/' in k)) for k in changed):
                raise ValueError('Faux changed a non-lighting resource; inspect the preserved backup')
            if diagnostic and any(before.get('tags/'+b['destination']) != after.get('tags/'+b['destination']) for b in plan['bsps']):
                raise ValueError('Diagnostic unexpectedly changed BSP geometry tags; inspect backup')
            report.update(status='GENERATED_PENDING_RUNTIME', after=after, changed_files=changed,
                seconds=time.perf_counter()-start, unchanged_outputs=len(before)-sum(k in before for k in changed))
            ownership.save('GENERATED', {k: v for k, v in after.items() if k not in preserved}, run.name)
        except Exception as exc:
            report.update(status='FAILED', failure=str(exc), traceback=traceback.format_exc(),
                seconds=time.perf_counter()-start, after=paths.snapshot())
            raise
        finally:
            # Persist the bake outcome before any cleanup that can itself fail.
            # A rejected restoration must not leave a finished run marked BAKING.
            flush()
            try:
                journal.finish(wait=True)
                flush()
                if (blob/'logs').exists():
                    shutil.copytree(blob/'logs', run/'faux-logs')
                if material_diagnostic or sun_control:
                    from port_environment.diagnostic_capture import capture_compare_restore
                    report['comparison'] = capture_compare_restore(paths, run, before, diagnostic_path, config, blob)
                    ownership.save('GENERATED', parent['files'], run.name+'-baseline-restored')
            except Exception as exc:
                report.update(status='FAILED_CLEANUP', cleanup_failure=str(exc),
                              cleanup_traceback=traceback.format_exc())
                raise
            finally:
                flush()
    print('BAKE_COMPARISON_COMPLETE', run)


if __name__ == '__main__':
    main(json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf-8-sig')))

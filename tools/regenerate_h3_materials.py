"""Rewrite existing generated shader tags only; default is a native dry run.

Uses the saved environment plan for destination identities and the resolved
shader manifest for semantic translation. Blender stages existing bitmap tag
references without reading, exporting or replacing texture pixels. All blocked
materials and non-material build files are fingerprinted and preserved.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'blender/addons/io_scene_foundry/h3_import'))
from port_environment.paths import OutputPaths, atomic_json, build_lock, digest
from port_environment.model import stable_hash


def fingerprint(path, *, hash_bytes=True):
    stat = path.stat()
    return dict(sha256=digest(path) if hash_bytes else None, mtime_ns=stat.st_mtime_ns, size=stat.st_size)


def snapshot(paths, extra=()):
    files = set(extra)
    for directory in [*paths.tag_directories(), paths.destination('data')]:
        for file in directory.rglob('*'):
            if file.is_symlink() or file.is_junction():
                raise ValueError('Redirected build path: '+str(file))
            if file.is_file():
                files.add(file)
    # Native tags (including every bitmap/lightmap) get byte hashes. Geometry
    # data is never opened by this worker and is monitored by size/timestamp;
    # avoid hashing many gigabytes of TIFF/GR2 data on a shader-only operation.
    return {str(file):fingerprint(file, hash_bytes=not file.is_relative_to(paths.roots['data'])) for file in sorted(files)}


def native_worker(config):
    from port_environment import object_worker
    plan = json.loads(Path(config['plan']).read_text())
    manifest = json.loads(Path(config['manifest']).read_text())
    paths = OutputPaths(config['h3_root'], config['reach_root'], plan['target']['namespace'], allow_nested=True)
    run = Path(config['output'])
    report = dict(status='PREFLIGHT', input_sha256={config[k]:digest(config[k]) for k in ('plan','manifest')},
        runtime_status='NOT_TESTED', shaders=[], failures=[], template_commands=[])
    object_worker.bootstrap(paths, run, report)
    import bpy
    from io_scene_foundry import utils
    from io_scene_foundry.managed_blam import Tag
    from io_scene_foundry.managed_blam.shader import ShaderTag
    from io_scene_foundry.h3_import.material_translation import H3MaterialRecord, translate
    from io_scene_foundry.h3_import.material_writer import writer_issues
    from io_scene_foundry.h3_import.reach_builder import ReachStager, read_destination_aliases
    from io_scene_foundry.h3_import.reach_materials import staged_image_name
    from io_scene_foundry.h3_import.port_environment.native_materials import complete_tag

    # Cover explicit TagFile.Save calls as well as Tag context autosaves.
    guard = dict(active=None)
    original_init = Tag.__init__
    class SaveGuard:
        def __init__(self, native, tag): self.native, self.owner = native, tag
        def __getattr__(self, name): return getattr(self.native, name)
        def Save(self):
            path = Path(str(self.owner.tag_path.Filename)).resolve()
            if path != guard['active'] or path.suffix != '.shader':
                raise ValueError('Material-only worker rejected tag write: '+str(path))
            return self.native.Save()
    def guarded_init(tag, *args, **kwargs):
        original_init(tag, *args, **kwargs)
        tag.tag = SaveGuard(tag.tag, tag)
        if tag.tag_is_new:
            tag.tag_has_changes = tag.always_save = False
            tag.tag.Dispose()
            raise ValueError('Material-only worker requires existing tags')
    Tag.__init__ = guarded_init

    def no_bitmap_export(*args, **kwargs):
        raise ValueError('Material-only worker forbids bitmap export/import')
    import io_scene_foundry.managed_blam.shader as shader_module
    import io_scene_foundry.tools.export_bitmaps as bitmap_module
    shader_module.export_bitmap = bitmap_module.export_bitmap = no_bitmap_export
    original_tool = utils.run_tool
    def template_only(arguments, *args, **kwargs):
        matching = [r for r in report.get('native_template_authoring', ())
                    if arguments == ['generate-specified-template','win',r['definition'],Path(r['template']).stem]]
        if guard['active'] is None or len(matching) != 1:
            raise ValueError('Material-only worker rejected Tool command: '+str(arguments))
        target = paths.owned_tag(matching[0]['template'])
        if target.exists() or not target.is_relative_to(paths.destination('tags', infrastructure=True)):
            raise ValueError('Template generation requires a missing owned template')
        report['template_commands'].append(arguments)
        return original_tool(arguments, *args, **kwargs)
    utils.run_tool = template_only

    # Also protect external lightmap references, if the current scenario uses any.
    extra, queue = set(), list(paths.destination('tags').glob('*.scenario*'))
    visited = set()
    while queue:
        file = queue.pop()
        if file in visited or not file.is_file(): continue
        visited.add(file)
        with Tag(path=str(file.relative_to(paths.roots['tags'])), tag_must_exist=True) as tag:
            for field in tag.tag.SelectTagFieldReferencesFast():
                if field.Path is None: continue
                target = Path(str(field.Path.Filename)).resolve()
                if target.is_file() and ('lightmap' in str(target).lower() or 'lightmap' in file.suffix.lower()):
                    extra.add(target)
                    if target.suffix != '.bitmap': queue.append(target)
    print('Fingerprinting protected tags and geometry data', flush=True)
    before = snapshot(paths, extra)
    atomic_json(run/'before.json', before)
    cache, staged = {}, {}

    class ExistingBitmaps(ReachStager):
        """Use production node/UV staging with native bitmap identities only."""
        def source_record(self, source): return adapted, manifest['shaders'][source['h3_source_shader']]
        def image(self, bitmap, parameter, source):
            identity = bindings[source['h3_source_shader']][parameter['name']]
            if identity not in self.images:
                image = self.remember(bpy.data.images, bpy.data.images.new('existing_'+Path(identity).stem, width=1, height=1))
                image.nwo.filepath = str(Path(identity).with_suffix('.tif'))
                image.nwo.reexport_tiff = False
                self.images[identity] = image
            return self.images[identity]
    # Only preview availability is adapted; shader records and bitmap identities
    # remain unchanged. The image override never opens these preview paths.
    adapted = dict(manifest, bitmaps={k:dict(v, preview='existing-native-bitmap') for k,v in manifest['bitmaps'].items()})
    bindings = {}
    stager = ExistingBitmaps()
    seen_sources, seen_targets = set(), set()
    for row in plan['materials']:
        source, destination = row['source_shader'], row['destination']
        file = paths.owned_tag(destination)
        if source in seen_sources or file in seen_targets or not file.is_file():
            raise ValueError('Missing or duplicate planned shader destination: '+destination)
        seen_sources.add(source); seen_targets.add(file)
        semantic = translate(H3MaterialRecord.from_resolved(manifest['shaders'][source], manifest['bitmaps']))
        entry = dict(source=source, destination=destination, absolute_path=str(file), before=before[str(file)],
            rule_id=semantic.rule_id, plan=semantic.to_dict(), action='PRESERVE_BLOCKED')
        report['shaders'].append(entry)
        declarations, notes = read_destination_aliases(semantic.to_dict()['options'], cache) if semantic.rule_id else ({}, [])
        issues = writer_issues(semantic, declarations) + notes
        if issues:
            entry['blockers'] = issues
            continue
        entry['action'] = 'REWRITE'
        if file.suffix != '.shader': raise ValueError('Eligible target must be an ordinary .shader')
        try:
            with ShaderTag(path=destination, tag_must_exist=True) as tag:
                declarations, notes = read_destination_aliases(semantic.to_dict()['options'], {}, definition_path=tag.definition.Path)
                if notes or writer_issues(semantic, declarations):
                    raise ValueError('Existing target RMOP contract differs: '+str(notes or writer_issues(semantic, declarations)))
                native = {p.SelectField('parameter name').GetStringData():p for p in tag.block_parameters.Elements}
                bindings[source] = {}
                entry['bitmap_bindings'] = []
                for name, parameter in semantic.payload['parameters'].items():
                    if parameter['type'] != 'bitmap': continue
                    field = native[name].SelectField('bitmap') if name in native else None
                    if field is None or field.Path is None: raise ValueError('Existing bitmap binding missing: '+name)
                    identity = str(field.Path.RelativePathWithExtension).replace('\\','/')
                    bitmap_file = Path(str(field.Path.Filename)).resolve()
                    if not bitmap_file.is_file() or bitmap_file.suffix != '.bitmap':
                        raise ValueError('Existing bitmap tag missing: '+identity)
                    source_bitmap = manifest['bitmaps'][parameter['bitmap']]
                    expected = paths.namespace+'/bitmaps/'+utils.valid_image_name(staged_image_name(source_bitmap,name))+'.bitmap'
                    binding = dict(parameter=name, source_bitmap=parameter['bitmap'], existing_target=identity,
                        expected_target=expected, source_identity_matches=identity==expected)
                    entry['bitmap_bindings'].append(binding)
                    if identity != expected:
                        missing_source = source_bitmap.get('status')=='error' and not paths.owned_tag(expected).exists()
                        policy = config.get('missing_source_bitmaps','error')
                        if not missing_source or policy=='error':
                            raise ValueError('Saved H3 bitmap identity differs from existing binding: '+str(binding))
                        binding.update(source_error=source_bitmap.get('error'), resolution=policy,
                            fidelity_loss='Source bitmap unavailable; existing Reach binding retained without texture replacement')
                        if policy=='preserve-shader': entry['action']='PRESERVE_MISSING_BITMAP'
                    bindings[source][name] = identity
                    extra.add(bitmap_file)
            if entry['action']=='PRESERVE_MISSING_BITMAP': continue
            material = bpy.data.materials.new('source_'+file.stem)
            material['h3_source_shader'] = source
            target = stager.build(material, semantic)
            if target is None: raise ValueError('Native staging failed: '+json.dumps(stager.results[-1]['diagnostics']))
            target.nwo.shader_path = destination
            staged[source] = target
            entry['staging'] = stager.results[-1]
        except Exception as exc:
            entry['preflight_error'] = str(exc)
            report['failures'].append(dict(source=source, stage='PREFLIGHT', error=str(exc)))
    for path in extra:
        before.setdefault(str(path), fingerprint(path))
    atomic_json(run/'before.json', before)
    report['rewrite_count'] = sum(r['action']=='REWRITE' for r in report['shaders'])
    report['preserve_count'] = len(report['shaders'])-report['rewrite_count']
    report['protected_write_policy'] = dict(scenario=False, bsp=False, structure_lighting_info=False,
        lightmap=False, sky_model=False, geometry_data=False, bitmap=False, faux=False,
        allowed='Only listed existing eligible .shader tags; missing owned native shader templates via generate-specified-template if required')
    report['missing_source_bitmap_policy'] = config.get('missing_source_bitmaps','error')
    report['geometry_data_verification'] = 'Size and modification timestamp; all native tags additionally checked by SHA-256'
    report['status'] = 'PREFLIGHT_FAILED' if report['failures'] else 'PREFLIGHT_CLEAN'
    atomic_json(run/'dry-run.json', report)
    lines = ['# Material-only dry run', '',f"Status: {report['status']}; rewrite: {report['rewrite_count']}; preserve: {report['preserve_count']}.", '',
        'No scenario, BSP, structure lighting, lightmap, sky model, geometry data, bitmap or Faux writes are permitted.', '',
        '| Action | Source | Exact existing destination | Error |','| --- | --- | --- | --- |']
    lines += [f"| {r['action']} | {r['source']} | {r['absolute_path']} | {r.get('preflight_error','')} |" for r in report['shaders']]
    (run/'dry-run.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('DRY_RUN',report['status'],report['rewrite_count'],report['preserve_count'],str(run/'dry-run.md'),flush=True)
    if report['failures'] or not config['apply']:
        report['protected_files_unchanged'] = snapshot(paths, extra)==before
        atomic_json(run/'result.json', report)
        return bool(report['failures'])

    # All inputs/destinations remain identical to the clean preflight. Back up
    # the complete rewrite set before the first native save, never blocked tags.
    if snapshot(paths, extra) != before: raise ValueError('Build files changed during preflight')
    for input_path, expected in report['input_sha256'].items():
        if digest(input_path) != expected: raise ValueError('Saved source JSON changed during preflight')
    for entry in report['shaders']:
        if entry['action'] != 'REWRITE': continue
        backup = run/'backups'/entry['destination']
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists(): raise FileExistsError(str(backup))
        shutil.copy2(entry['absolute_path'], backup)
        if fingerprint(backup) != entry['before']: raise ValueError('Backup verification failed: '+str(backup))
        entry['backup'] = str(backup)
    atomic_json(run/'result.json', report)
    for index,entry in enumerate(r for r in report['shaders'] if r['action']=='REWRITE'):
        file = Path(entry['absolute_path'])
        print(f"Rewriting shader {index+1}/{report['rewrite_count']}: {entry['destination']}", flush=True)
        guard['active'] = file
        try:
            if fingerprint(file) != entry['before']: raise ValueError('Shader changed since backup')
            complete_tag(staged[entry['source']], manifest, report, paths)
            entry['status'] = 'REWRITTEN_VERIFIED'
            entry['readback'] = report['native_material_completion'][-1]['readback']
        except Exception as exc:
            shutil.copy2(entry['backup'], file)
            entry.update(status='FAILED_RESTORED', error=str(exc), traceback=traceback.format_exc())
            report['failures'].append(dict(source=entry['source'], stage='WRITE', error=str(exc)))
            if fingerprint(file) != entry['before']: raise RuntimeError('Shader rollback failed: '+str(file))
        finally:
            guard['active'] = None
        entry['after'] = fingerprint(file)
        atomic_json(run/'result.json', report)
    print('Verifying protected tag/data hashes and timestamps', flush=True)
    after = snapshot(paths, extra)
    atomic_json(run/'after.json', after)
    rewritten = {r['absolute_path'] for r in report['shaders'] if r.get('status')=='REWRITTEN_VERIFIED'}
    changed_protected = [name for name, value in before.items() if name not in rewritten and after.get(name)!=value]
    added = [name for name in after if name not in before]
    infrastructure = paths.destination('tags', infrastructure=True)
    illegal_added = [name for name in added if not Path(name).is_relative_to(infrastructure) or
        Path(name).suffix not in {'.render_method_template','.pixel_shader','.vertex_shader','.render_method_definition'}]
    report.update(protected_files_unchanged=not changed_protected and not illegal_added,
        changed_protected=changed_protected, unexpected_new_files=illegal_added, generated_infrastructure=added,
        rewritten_count=len(rewritten), preserved_blocked_count=sum(r['action']=='PRESERVE_BLOCKED' for r in report['shaders']),
        protected_file_counts=dict(Counter(Path(name).suffix for name in before if name not in rewritten)))
    for entry in report['shaders']:
        if entry['action']=='PRESERVE_BLOCKED':
            entry.update(status='PRESERVED_BLOCKED', after=after.get(entry['absolute_path']))
        elif entry['action']=='PRESERVE_MISSING_BITMAP':
            entry.update(status='PRESERVED_MISSING_BITMAP', after=after.get(entry['absolute_path']))
    report['status'] = 'COMPLETE' if not report['failures'] and report['protected_files_unchanged'] else 'FAILED'
    atomic_json(run/'result.json', report)
    print('MATERIAL_ONLY_RESULT',json.dumps({k:report[k] for k in ('status','rewritten_count','preserved_blocked_count','protected_files_unchanged','generated_infrastructure','failures')}),flush=True)
    return report['status']!='COMPLETE'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('plan','manifest','h3-root','reach-root','blender','output'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--apply', action='store_true', help='Rewrite only after the native dry-run report is clean')
    parser.add_argument('--missing-source-bitmaps', choices=('error','preserve-binding','preserve-shader'), default='error',
        help='Explicit policy for existing binding mismatches where the saved manifest records a missing source bitmap')
    args = parser.parse_args()
    config = {k:str(Path(v).resolve(strict=k!='output')) if isinstance(v,str) and k!='missing_source_bitmaps' else v for k,v in vars(args).items()}
    plan = json.loads(Path(config['plan']).read_text())
    if stable_hash({k:v for k,v in plan.items() if k!='plan_sha256'}) != plan['plan_sha256']:
        raise ValueError('Saved environment plan integrity differs')
    paths = OutputPaths(config['h3_root'],config['reach_root'],plan['target']['namespace'],allow_nested=True)
    if paths.fingerprint()!=plan['target']['project_fingerprint']:
        raise ValueError('Saved plan belongs to a different Reach checkout')
    run = Path(config['output'])
    if run.exists() or run.is_relative_to(paths.h3) or run.is_relative_to(paths.reach):
        raise ValueError('Use a new report directory outside both editing kits')
    key = paths.fingerprint()+'-'+stable_hash(paths.namespace)[:16]
    with build_lock(Path(tempfile.gettempdir())/'foundry_h3_port_locks'/key):
        run.mkdir(parents=True)
        atomic_json(run/'config.json',config)
        command = [config['blender'],'--background','--factory-startup','--python-exit-code','1',
            '--python',str(Path(__file__).resolve()),'--','--worker',str(run/'config.json')]
        print('Material-only report: '+str(run),flush=True)
        with (run/'worker.log').open('x',encoding='utf-8') as log:
            result = subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,cwd=paths.reach)
        print('Worker exit:',result.returncode,'; report:',run/'result.json',flush=True)
        return result.returncode


if __name__=='__main__':
    if '--worker' in sys.argv:
        if native_worker(json.loads(Path(sys.argv[-1]).read_text())):
            raise RuntimeError('Material-only operation failed; inspect the dry-run/result report')
    else:
        sys.exit(main())

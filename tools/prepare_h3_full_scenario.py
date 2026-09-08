"""Prepare a complete source plan, reusing a sealed original material snapshot.

This only writes a new evidence directory. Native authoring is performed by
the existing environment compiler after the source contracts pass. Existing
stage outputs may be reused only with their completed hash receipts.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment import fixtures, scenario_ir, snapshot, model, dependencies, seam_states
from port_environment.paths import OutputPaths, atomic_json, digest, relative


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sealed_copy(source, target):
    source = Path(source).resolve(strict=True)
    target = Path(target)
    if target.exists():
        if digest(target) != digest(source):
            raise ValueError('Existing evidence differs: '+str(target))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


class Stages:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def run(self, name, command, cwd, outputs, inputs):
        command = [str(v) for v in command]
        expected = dict(command=command, inputs={str(p):digest(p) for p in inputs})
        receipt = self.directory/(name+'.receipt.json')
        if receipt.exists():
            old = read(receipt)
            if any(old[k] != v for k,v in expected.items()):
                raise ValueError('Source stage inputs changed: '+name)
            snapshot.verify_files(old['outputs'])
            print('Reused '+name, flush=True)
            return
        if any(Path(p).exists() for p in outputs):
            raise ValueError('Unsealed partial source output: '+name)
        log = self.directory/(name+'.log')
        attempt = 1
        while log.exists():
            attempt += 1
            log = self.directory/(name+f'.attempt-{attempt:02}.log')
        print('Running '+name, flush=True)
        begin = time.monotonic()
        with log.open('xb') as stream:
            result = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f'{name} exited {result.returncode}: {log}')
        expected.update(outputs={str(p):digest(p) for p in outputs}, seconds=time.monotonic()-begin, exit_code=0)
        atomic_json(receipt, expected)


def prepare(args):
    run = Path(args.output).resolve()
    paths = OutputPaths(args.h3_root, args.reach_root, args.namespace, allow_nested=True)
    if run.is_relative_to(paths.h3) or run.is_relative_to(paths.reach):
        raise ValueError('Evidence directory must be outside the kits')
    if (run/'environment.plan.json').exists():
        raise ValueError('Completed source plans are immutable; choose a new directory')
    run.mkdir(parents=True, exist_ok=True)
    stages = Stages(run/'stages')
    preserved_path = Path(args.preserved_plan).resolve(strict=True)
    preserved = read(preserved_path)
    original_paths = OutputPaths(args.h3_root, args.reach_root, preserved['target']['namespace'], allow_nested=True)
    preserved, old_manifest, receipt = snapshot.load(preserved_path, original_paths,
        args.scenario, preserved['selection']['source_zone_set'])
    old_run = Path(receipt['source_run'])
    source_xml = Path(args.scenario_xml).resolve(strict=True)
    sealed_copy(source_xml, run/'scenario.xml')
    root = fixtures.read_authoring(source_xml, scenario_ir.FIELDS | {'scenario resources'})
    selected = scenario_ir.select_all(root, args.scenario, args.initial_zone, args.spawn_flag)
    atomic_json(run/'selection.plan.json', selected)
    decoded = Path(args.decoded_source).resolve(strict=True)
    scene = read(decoded/'scene.h3scene.json')
    if scene['source_tag'] != args.scenario:
        raise ValueError('Decoded source belongs to a different scenario')
    source_hashes = {str(paths.source(args.scenario)):digest(paths.source(args.scenario))}
    bsps = []
    for row in selected['bsps']:
        entry = next(e for e in scene['bsp_entries'] if e['index'] == row['source_index'])
        if entry['status'] != 'extracted' or entry['source_tag'] != row['source_tag']:
            raise ValueError('Required BSP was not decoded: '+str(entry))
        geometry = decoded/relative(entry['geometry'])
        sealed_copy(geometry, run/'source'/relative(entry['geometry']))
        bsp = read(geometry)
        accepted = next((b for b in preserved['bsps'] if b['source_index']==row['source_index']), None)
        if accepted and model.stable_hash(bsp) != accepted['geometry_source']['canonical_sha256']:
            raise ValueError('Existing accepted BSP source changed: '+row['source_tag'])
        bsps.append(bsp)
        source_hashes[str(paths.source(row['source_tag']))] = digest(paths.source(row['source_tag']))
    sealed_copy(decoded/'scene.h3scene.json', run/'source/scene.h3scene.json')
    helpers = Path(args.helpers).resolve(strict=True)
    def xml(name, tag):
        target = run/(name+'.xml')
        source = paths.source(tag)
        stages.run(name, [paths.h3/'tool.exe','export-tag-to-xml',source,target], paths.h3,
                   [target], [source, paths.h3/'tool.exe'])
        source_hashes[str(source)] = digest(source)
        return fixtures.parse(target.read_bytes())
    lighting, designs, sky_xmls, sky_renders, lights, skies = {}, {}, {}, {}, {}, []
    for row in selected['bsps']:
        lighting[row['lighting_info']] = xml('lighting-'+str(row['source_index']), row['lighting_info'])
        if row['structure_design'] and row['structure_design'] not in designs:
            designs[row['structure_design']] = xml('design-'+str(row['source_index']), row['structure_design'])
    seams = xml('seams', selected['structure_seams']) if selected['structure_seams'] else None
    for row in selected['skies']:
        old = next((s for s in preserved['skies'] if s['source_scenery']==row['source_tag']), None)
        if old is None:
            raise ValueError('Additional sky requires a separately verified source decode: '+row['source_tag'])
        sky = read(old_run/f"sky/sky-{row['source_index']}/asset.h3asset.json")
        skies.append(sky)
        sky_xmls[row['source_tag']] = xml('sky-'+str(row['source_index']),row['source_tag'])
        sky_renders[row['source_tag']] = xml('sky-render-'+str(row['source_index']),sky['dependencies']['render_model'])
    for row in selected['light_palette']:
        if row['source_tag'] and row['source_tag'] not in lights:
            lights[row['source_tag']] = xml('light-'+str(row['source_index']),row['source_tag'])
    needed = model.used_shaders(bsps, skies)
    new = sorted(set(needed)-old_manifest['shaders'].keys())
    materials = run/'materials'; materials.mkdir(exist_ok=True)
    fresh = materials/'additional'; fresh.mkdir(exist_ok=True)
    request = dict(scene, shader_paths=new)
    request_path = fresh/'request.json'
    if request_path.exists() and read(request_path) != request:
        raise ValueError('Additional material request changed')
    atomic_json(request_path, request)
    if new:
        stages.run('additional-shaders', [helpers/'h3-shader-bridge.exe','--asset',request_path,
            '--tags-root',paths.h3_tags,'--reach-tags-root',paths.roots['tags'],'--output',fresh,'--single-image-pixels'],
            helpers, [fresh/'shader_manifest.json'], [request_path,helpers/'h3-shader-bridge.exe',*(paths.source(s) for s in new)])
        extra = read(fresh/'shader_manifest.json')
    else:
        extra = dict(shaders={},bitmaps={})
    merged = {k:deepcopy(v) for k,v in old_manifest.items() if k not in {'shaders','bitmaps','environment_dependencies','timings','cache'}}
    merged['shaders'] = {s:deepcopy(old_manifest['shaders'].get(s,extra['shaders'].get(s))) for s in needed}
    merged['bitmaps'] = {}
    for manifest, directory, prefix in [(extra,fresh,'additional'),(old_manifest,old_run/'materials','original')]:
        for key, original in manifest['bitmaps'].items():
            row = deepcopy(original)
            for name in ('preview','dds','tiff'):
                if row.get(name):
                    source = directory/relative(row[name])
                    target = materials/prefix/relative(row[name])
                    if source.resolve() != target.resolve():
                        sealed_copy(source,target)
                    row[name] = prefix+'/'+relative(row[name]).as_posix()
            if row.get('cube_source'):
                source = directory/relative(row['cube_source']['tiff'])
                target = materials/prefix/relative(row['cube_source']['tiff'])
                sealed_copy(source,target)
                row['cube_source']['tiff'] = target.relative_to(materials).as_posix()
            merged['bitmaps'][key] = row
    for key,row in merged['bitmaps'].items():
        if row.get('type')!='cube map' or row.get('cube_source'):
            continue
        cube = materials/'cube-authoring'/model.stable_hash(key)[:16]
        cube.mkdir(parents=True,exist_ok=True)
        source = paths.source(row['path'].replace('\\','/')+'.bitmap')
        stages.run('cube-'+cube.name,[helpers/'h3-bitmap-authoring.exe',paths.h3_tags,source,cube],
                   helpers,[cube/'bitmap-authoring.json',cube/'source_cube.tif'],
                   [source,helpers/'h3-bitmap-authoring.exe'])
        recovered = read(cube/'bitmap-authoring.json')
        if recovered['source_sha256']!=digest(source) or recovered['format']!=row['format']:
            raise ValueError('Supplemental source cubemap identity differs')
        row['cube_source'] = recovered['cube_source']
        row['cube_source']['tiff'] = (cube/'source_cube.tif').relative_to(materials).as_posix()
        row['status'] = recovered['status']
    print(f"Materials: {len(needed)-len(new)} preserved recipes, {len(new)} additional recipes",flush=True)
    original_manifest = materials/'shader_manifest.json'
    atomic_json(original_manifest, merged)
    inventory = dependencies.TagInventory(paths.h3_tags)
    cache_path = run/'cache-dependency-evidence.json'
    cache_records = read(cache_path) if cache_path.exists() else []
    merged, dependency_report = dependencies.audit(merged,bsps,skies,selected,inventory,cache_records)
    dependency_report['preserved_original_recipe_basis'] = dict(plan=str(preserved_path),sha256=digest(preserved_path),
        source_recipe_sha256=digest(old_run/'materials/authoring-shader-manifest.json'),
        source_shaders=sorted(set(needed)&old_manifest['shaders'].keys()),
        original_dependency_decisions=old_manifest.get('environment_dependencies',{}))
    atomic_json(materials/'authoring-shader-manifest.json',merged)
    atomic_json(run/'source-dependencies.json',dependency_report)
    context = seam_states.discover_neighbors(root,bsps,seams,lambda *args:None) if seams is not None else {}
    plan = assemble(run, paths, scene, bsps, skies, merged, root, lighting, sky_xmls, sky_renders,
                    selected, designs, seams, lights, context)
    # Metadata and pixels, not the currently edited loose shader, are the input
    # for every original recipe reused above. Correct its provenance explicitly.
    for source in set(needed)&old_manifest['shaders'].keys():
        plan['source']['hashes'][source] = preserved['source']['hashes'][source]
    for row in plan['source_semantic_resolution']['records']:
        source = row['original_record']['source_tag'].replace('\\','/')
        row['provenance']['source_sha256'] = plan['source']['hashes'].get(source)
        row['provenance']['full_scenario'] = True
    inputs = dict(receipt['verified_files'])
    inputs.update({str(p):digest(p) for p in run.glob('*.xml')})
    if cache_records:
        inputs[str(cache_path)] = digest(cache_path)
    inputs.update({str(p):digest(p) for p in materials.rglob('*') if p.is_file()})
    # Recheck all newly decoded source dependencies, except original recipes
    # intentionally pinned to the preserved snapshot rather than loose edits.
    for source, expected in plan['source']['hashes'].items():
        if source not in old_manifest['shaders']:
            path = paths.source(source)
            if digest(path) != expected:
                raise ValueError('Source changed during planning: '+source)
            inputs[str(path)] = expected
    plan['source_validation_basis'] = dict(basis='Preserved original shader recipes plus fresh complete scenario decode',
        source_run=str(run), input_sha256=inputs, protected_original_plan=str(preserved_path))
    plan['plan_sha256'] = model.stable_hash({k:v for k,v in plan.items() if k!='plan_sha256'})
    if plan['unsupported']:
        blocked = run/'environment.blocked.json'
        atomic_json(blocked,plan,compact=True)
    else:
        atomic_json(run/'environment.plan.json',plan,compact=True)
    atomic_json(run/'unsupported-semantics.json',plan['unsupported'])
    atomic_json(run/'source-semantic-resolution.json',plan['source_semantic_resolution'])
    summary = dict(bsps=len(plan['bsps']),zones=len(selected['zone_sets']),seams=len(plan['seams']),
        materials=len(plan['materials']),bitmaps=len(plan['bitmaps']),
        blocking_contracts=len(plan['unsupported']),plan_sha256=plan['plan_sha256'],
        target=plan['target']['scenario'],native_status='NOT_GENERATED')
    atomic_json(run/'prepare-report.json',summary)
    print(json.dumps(summary,indent=2),flush=True)


def assemble(run, paths, scene, bsps, skies, merged, root, lighting, sky_xmls, sky_renders,
             selected, designs, seams, lights, context):
    from port_environment import semantics
    original = semantics.report
    def capture(records, decisions, baseline=None):
        atomic_json(run/'source-contract-attempt.json',dict(records=records,decisions=decisions))
        return original(records,decisions,baseline)
    semantics.report = capture
    try:
        return model.construct(paths,scene,bsps,skies,merged,root,lighting,sky_xmls,sky_renders,
            lighting_quality='direct_only',selection=selected,designs=designs,seams_xml=seams,
            light_xmls=lights,seam_source_context=context)
    finally:
        semantics.report = original


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('h3-root','reach-root','output','preserved-plan','scenario-xml','decoded-source','helpers'):
        p.add_argument('--'+name,required=True)
    p.add_argument('--scenario',default='levels/solo/040_voi/040_voi.scenario')
    p.add_argument('--namespace',default='levels/h3_port/040_voi/full_scenario')
    p.add_argument('--initial-zone',default='intro_faa')
    p.add_argument('--spawn-flag',default='teleport_factorya_player0')
    prepare(p.parse_args())


if __name__ == '__main__':
    main()

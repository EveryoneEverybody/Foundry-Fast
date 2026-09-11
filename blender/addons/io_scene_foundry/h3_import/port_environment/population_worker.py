"""Populate through verified root receipts; save/reopen and Tool XML verification."""
import json
from pathlib import Path
import subprocess
import sys
import traceback

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = 'port_environment'

from . import native_population, native_placements, object_worker, population_xml, scenario_ir
from .model import stable_hash
from .paths import OutputPaths, atomic_json, digest
from .snapshot import verify_files
from .object_receipts import reusable_root, rule_fingerprint


def main():
    config = json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
    run = Path(config['run_directory'])
    read = lambda p: json.loads(Path(p).read_text())
    report = dict(status='BUILDING', runtime_status='NOT_TESTED')
    try:
        verify_files(config['inputs'])
        plan, inventory = read(config['plan']), read(config['inventory'])
        receipts = read(config['root_receipts'])
        paths = OutputPaths(config['h3_root'], config['reach_root'], plan['target']['namespace'], allow_nested=True)
        if stable_hash({k:v for k,v in inventory.items() if k!='inventory_sha256'})!=inventory['inventory_sha256']:
            raise ValueError('Source scenario inventory integrity differs')
        if digest(paths.h3_tags/inventory['source_scenario'])!=inventory['source_sha256']:
            raise ValueError('Source scenario changed since inventory')
        if digest(plan['environment_plan'])!=plan['environment_plan_sha256']:
            raise ValueError('Environment index contract changed')
        environment=read(plan['environment_plan'])
        compiled, objects = {}, {r['source_tag']:dict(r) for r in plan['objects']}
        hashes={}
        def current_hash(path):
            if path not in hashes:hashes[path]=digest(path) if Path(path).is_file() else None
            return hashes[path]
        for source, receipt in receipts.items():
            if source not in objects:
                raise ValueError('Receipt source is outside the object plan')
            row = objects[source]
            if receipt['identity']['rule_fingerprint'] != rule_fingerprint(row):
                raise ValueError('Root authoring rule fingerprint changed: '+source)
            if any(current_hash(p)!=h for p,h in receipt['identity']['source_hashes'].items()):
                raise ValueError('Source closure changed: '+source)
            current = {p:current_hash(p) for p in receipt['output_files']}
            if not reusable_root(receipt, row['reuse_identity'], current):
                raise ValueError('Root receipt differs from current source/rules/output: ' + source)
            compiled[source] = dict(source_tag=source, target_tag=row['target_tag'], status='NATIVE_COMPILED')
        translation = native_placements.plan(inventory, compiled, objects)
        atomic_json(run/'source-translation.json', translation)
        object_worker.bootstrap(paths, run, report)
        from io_scene_foundry.managed_blam.scenario import ScenarioTag
        scenario = paths.owned_tag(paths.scenario+'.scenario')
        before_sha = digest(scenario)
        if before_sha != config['scenario_before_sha256']:
            raise ValueError('Scenario changed after protected baseline')
        before = population_xml.read(config['before_xml'])
        provenance = read(config['provenance']).get('placements', {}) if config.get('provenance') else {}
        with ScenarioTag(path=paths.scenario+'.scenario', tag_must_exist=True) as tag:
            bsps=tag.tag.SelectField('structure bsps').Elements
            if bsps.Count!=len(environment['bsps']):raise ValueError('Installed BSP index contract differs')
            for bsp in environment['bsps']:
                if bsp['source_index']!=bsp['target_index']:
                    raise ValueError('Nonidentity BSP placement membership needs an explicit mapping adapter')
                path=bsps[bsp['target_index']].SelectField('structure bsp').Path
                if path is None or str(path.RelativePathWithExtension).replace('\\','/')!=bsp['destination']:
                    raise ValueError('Installed BSP identity differs from placement contract')
            result = native_population.plan(tag, translation, before['placement_fingerprints'],
                                            families=config['families'], provenance=provenance)
            atomic_json(run/'population-plan.json', result)
            if config['dry_run']:
                report.update(status='DRY_RUN', semantic_mutations=result['semantic_mutation_count'])
                return
            report['authoring'] = native_population.apply(tag, result, translation)
        with ScenarioTag(path=paths.scenario+'.scenario', tag_must_exist=True) as tag:
            for row in result['placements']:
                native_population.verify_element(tag.tag.SelectField(row['family']).Elements[row['target_index']], row)
                palette=tag.tag.SelectField(scenario_ir.FAMILIES[row['family']][0]).Elements
                path=palette[row['target_palette_index']].SelectField('name').Path
                if path is None or str(path.RelativePathWithExtension).replace('\\','/')!=compiled[row['source_tag']]['target_tag']:
                    raise ValueError('Reopened native palette root differs')
                ni=row['target_object_name_index']
                if ni>=0 and tag.tag.SelectField('object names').Elements[ni].SelectField('name').GetStringData()!=row['source_object_name']:
                    raise ValueError('Reopened native object name differs')
            for source_index, target_index in result['device_group_map'].items():
                source = next(r for r in translation['device_groups'] if r['source_index'] == int(source_index))
                native_placements.verify_xml(source['source_records'], tag.tag.SelectField('device groups').Elements[target_index],
                                             ('name','initial value','flags'))
        xml = run/'native-scenario.xml'
        with (run/'tool-export.log').open('wb') as log:
            tool = subprocess.run([str(paths.reach/'tool.exe'),'export-tag-to-xml',str(scenario),str(xml)],
                                  cwd=paths.reach, stdout=log, stderr=subprocess.STDOUT)
        if tool.returncode:
            raise ValueError('Native scenario Tool XML export failed')
        after = population_xml.read(xml)
        population_xml.verify_preservation(before, after, result)
        report['tool_xml_validation']=population_xml.verify_expected(before,after,result,compiled)
        provenance = dict(source_scenario=inventory['source_scenario'], source_sha256=inventory['source_sha256'], placements={})
        for row in result['placements']:
            provenance['placements'][row['logical_id']] = dict(
                source_scenario=inventory['source_scenario'], source_sha256=inventory['source_sha256'],
                source_index=row['source_index'], source_palette_index=row['source_palette_index'],
                source_tag=row['source_tag'], unique_id=row.get('unique_id'), family=row['family'],
                target_index=row['target_index'], target_palette_index=row['target_palette_index'],
                target_object_name_index=row['target_object_name_index'],
                target_fingerprint=after['placement_fingerprints'][row['family']][row['target_index']])
        atomic_json(run/'placement-provenance.json', provenance)
        after_sha = digest(scenario)
        if not result['semantic_mutation_count'] and before_sha != after_sha:
            raise ValueError('Zero-mutation population changed scenario bytes')
        report.update(status='NATIVE_AUTHORED_READBACK_VERIFIED', scenario_before_sha256=before_sha,
                      scenario_after_sha256=after_sha, byte_identical=before_sha==after_sha,
                      semantic_mutations=result['semantic_mutation_count'],
                      protected_scenario_sections='VERIFIED', reused_roots=len(compiled),
                      placements=result['placements'], deferred=result['deferred'])
    except Exception as exc:
        report.update(status='FAILED', reason=str(exc), traceback=traceback.format_exc())
        raise
    finally:
        atomic_json(run/'population-result.json', report)


if __name__ == '__main__':
    main()

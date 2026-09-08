"""Integrate only verified non-unit dependency chains in the owned scenario."""
import json
from pathlib import Path
import sys
import traceback

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent));__package__='port_environment'
from . import object_worker,worker,native_placements
from .model import stable_hash
from .paths import OutputPaths,atomic_json,digest
from .snapshot import verify_files


def main():
    config=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text());run=Path(config['run_directory'])
    plan=json.loads(Path(config['plan']).read_text());source=json.loads(Path(config['inventory']).read_text())
    receipt=json.loads(Path(config['compiled_report']).read_text())
    if receipt['status']!='COMPLETE' or receipt['plan_sha256']!=plan['plan_sha256']:
        raise ValueError('Native dependency batch is incomplete or from a different object plan')
    if stable_hash({k:v for k,v in source.items() if k!='inventory_sha256'})!=source['inventory_sha256']:
        raise ValueError('Source placement inventory integrity differs')
    verify_files(plan['source_files'])
    if digest(plan['environment_plan'])!=plan['environment_plan_sha256']:raise ValueError('Environment plan differs')
    environment=json.loads(Path(plan['environment_plan']).read_text())
    compiled={r['source_tag']:r for r in receipt['worker']['objects'] if r['status']=='NATIVE_COMPILED'}
    translation=native_placements.plan(source,compiled,{r['source_tag']:r for r in plan['objects']})
    atomic_json(run/'placement-plan.json',translation)
    paths=OutputPaths(config['h3_root'],config['reach_root'],plan['target']['namespace'],allow_nested=True)
    report=dict(status='BUILDING',runtime_status='NOT_TESTED',tool_invocations=[],source_inventory_sha256=digest(config['inventory']),
        native_object_receipt_sha256=digest(config['compiled_report']))
    flush=lambda:atomic_json(run/'worker-report.json',report)
    journal=None
    try:
        object_worker.bootstrap(paths,run,report);journal=worker.ToolJournal(paths,run,report,flush)
        from io_scene_foundry.managed_blam.scenario import ScenarioTag
        from io_scene_foundry import utils
        with ScenarioTag(path=paths.scenario+'.scenario',tag_must_exist=True) as tag:
            report['authoring']=native_placements.configure(tag,translation,environment)
        with ScenarioTag(path=paths.scenario+'.scenario',tag_must_exist=True) as tag:
            report['native_validation']=native_placements.validate(tag,translation,environment)
        xml=run/'native-scenario.xml'
        utils.run_tool(['export-tag-to-xml',str(paths.owned_tag(paths.scenario+'.scenario')),str(xml)],force_tool=True)
        journal.finish(wait=True)
        if not xml.is_file() or any(t['exit_code']!=0 for t in report['tool_invocations']):raise ValueError('Native scenario Tool XML validation failed')
        report.update(status='COMPLETE',tool_xml=str(xml),tool_xml_sha256=digest(xml))
        translation.update(native_status='NATIVE_SCENARIO_INTEGRATED',runtime_status='NOT_TESTED')
        for f in native_placements.SUPPORTED:
            for r in translation['families'][f]['placements']:
                if r['native_status']=='READY':r['native_status']='NATIVE_AUTHORED_READBACK_VERIFIED'
        atomic_json(run/'scenario-translation.json',translation)
    except Exception as exc:
        report.update(status='FAILED',failure=str(exc),traceback=traceback.format_exc());traceback.print_exc()
    finally:
        if journal:journal.finish(wait=True)
        flush()
    if report['status']!='COMPLETE':raise RuntimeError(report['failure'])


if __name__=='__main__':main()

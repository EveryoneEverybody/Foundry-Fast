"""Reuse only imported bitmap outputs covered by the previous owned build receipt."""
import json
from pathlib import Path
from .paths import digest
from .native_bitmaps import PIXEL_EXPORT


def previous_bitmaps(paths,plan,config,identities=None):
    directory=Path(config['report_directory'])
    latest=directory/(paths.asset+'_build_report.json')
    candidates=[latest,*sorted((directory/'runs').glob('*/'+latest.name),reverse=True)]
    result={}
    for report in candidates:
        result.update(_from_report(paths,plan,config,report,set(result)))
        if identities is not None and set(identities)<=set(result):break
    return result


def _from_report(paths, plan, config, report,skip):
    if not report.is_file() or not config.get('snapshot_input'):
        return {}
    previous=json.loads(report.read_text(encoding='utf-8'))
    if (previous.get('plan_sha256')!=plan['plan_sha256'] or
        previous.get('source_validation_basis',{}).get('verified_files')!=config['snapshot_input']['verified_files']):
        return {}
    hashes={r['path']:r['sha256'] for r in previous.get('generated_files',[])}
    accepted={r['command'][2].replace('\\','/') for r in previous.get('worker',{}).get('tool_invocations',[])
        if r.get('status')=='ACCEPTED' and len(r.get('command',[]))>2 and r['command'][1]=='reimport-bitmaps-single'}
    accepted.update(previous.get('worker',{}).get('bitmap_cache_reused',[]))
    result={}
    bitmap_rows={str(Path(r['destination']).with_suffix('')).replace('\\','/'):r for r in previous.get('worker',{}).get('bitmap_builds',[])}
    cube_sources={key.rsplit('#',1)[0] for key,spec in plan['bitmaps'].items() if spec.get('source_layout')}
    for name in accepted:
        if name in skip:continue
        if not name.startswith(paths.namespace+'/'):
            continue
        row=bitmap_rows.get(name,{})
        if row.get('pixel_export')!=PIXEL_EXPORT:
            continue
        if row.get('source_bitmap','').replace('\\','/') in cube_sources and row.get('native_cube_layout')!='reach_cross_frblud_v1':
            continue
        checked={}
        for kind,extension in [('data','.tif'),('tags','.bitmap')]:
            path=paths.destination(kind,name[len(paths.namespace)+1:]+extension)
            expected=hashes.get(kind+'/'+name+extension)
            if not expected or not path.is_file() or digest(path)!=expected:
                break
            checked[kind]=str(path)
        else:
            result[name]=checked
    return result

"""Resolve an unsealed full-scenario plan after a translation rule was added.

Reuse verified source authoring and decoded geometry; never re-export source
tags or overwrite a completed plan. Reconstruct the complete contract report.
"""
import argparse
from pathlib import Path
from prepare_h3_full_scenario import read, assemble, fixtures, scenario_ir, snapshot, model, seam_states, OutputPaths, atomic_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('blocked_plan')
    parser.add_argument('output_plan')
    parser.add_argument('--h3-root',required=True)
    parser.add_argument('--reach-root',required=True)
    args=parser.parse_args()
    old=read(args.blocked_plan);run=Path(args.blocked_plan).resolve().parent
    output=Path(args.output_plan).resolve()
    if old['selection'].get('scope')!='FULL_SCENARIO' or not old['unsupported'] or output.exists():
        raise ValueError('Require a blocked full-scenario plan and a new output filename')
    if model.stable_hash({k:v for k,v in old.items() if k!='plan_sha256'})!=old['plan_sha256']:
        raise ValueError('Original blocked plan integrity mismatch')
    snapshot.verify_files(old['source_validation_basis']['input_sha256'])
    paths=OutputPaths(args.h3_root,args.reach_root,old['target']['namespace'],allow_nested=True)
    if paths.fingerprint()!=old['target']['project_fingerprint']:
        raise ValueError('Target project differs from blocked plan')
    selected=old['selection'];bsps=[]
    for b in old['bsps']:
        decoded=read(run/'source'/b['geometry_source']['file'])
        if model.stable_hash(decoded)!=b['geometry_source']['canonical_sha256']:
            raise ValueError('Source geometry changed')
        bsps.append(decoded)
    root=fixtures.read_authoring(run/'scenario.xml',scenario_ir.FIELDS|{'scenario resources'})
    def xml(name):return fixtures.parse((run/(name+'.xml')).read_bytes())
    lighting={b['lighting_info']:xml('lighting-'+str(b['source_index'])) for b in selected['bsps']}
    designs={b['structure_design']:xml('design-'+str(b['source_index'])) for b in selected['bsps'] if b['structure_design']}
    sky_xmls={s['source_tag']:xml('sky-'+str(s['source_index'])) for s in selected['skies']}
    sky_renders={s['source_tag']:xml('sky-render-'+str(s['source_index'])) for s in selected['skies']}
    preserved=read(old['source_validation_basis']['protected_original_plan'])
    sky_run=Path(preserved['source_validation_basis']['source_run'])
    skies=[read(sky_run/f"sky/sky-{s['source_index']}/asset.h3asset.json") for s in selected['skies']]
    lights={s['source_tag']:xml('light-'+str(s['source_index'])) for s in selected['light_palette'] if s['source_tag']}
    seams=xml('seams');context=seam_states.discover_neighbors(root,bsps,seams,lambda *args:None)
    plan=assemble(run,paths,read(run/'source/scene.h3scene.json'),bsps,skies,
        read(run/'materials/authoring-shader-manifest.json'),root,lighting,sky_xmls,sky_renders,selected,designs,seams,lights,context)
    plan['source']['hashes']=old['source']['hashes']
    plan['source_validation_basis']=old['source_validation_basis']
    for r in plan['source_semantic_resolution']['records']:
        source=r['original_record']['source_tag'].replace('\\','/')
        r['provenance']['source_sha256']=plan['source']['hashes'].get(source)
        r['provenance']['full_scenario']=True
    plan['plan_sha256']=model.stable_hash({k:v for k,v in plan.items() if k!='plan_sha256'})
    atomic_json(output,plan,compact=True)
    print(dict(plan=str(output),blocking=len(plan['unsupported']),bsps=len(plan['bsps']),zones=len(selected['zone_sets'])),flush=True)


if __name__=='__main__':main()

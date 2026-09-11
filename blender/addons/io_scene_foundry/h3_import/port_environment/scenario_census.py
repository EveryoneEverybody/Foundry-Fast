"""Source counts and specialized presentation evidence beyond modeled families."""
from collections import Counter
import html
import re
from . import fixtures, scenario_ir


SPECIALIZED = {
    'decorators': 'Decorator placement/set translation',
    'decals': 'Decal placement translation',
    'decal palette': 'Decal root/material translation',
    'atmosphere': 'Atmosphere/fog semantic mapping',
    'acoustics palette': 'Environment acoustics',
    'camera fx palette': 'Camera presentation',
    'cinematic lighting palette': 'Cinematic lighting',
    'cinematics': 'Cinematic graphs and environmental objects',
    'cortana effects': 'Scripted presentation effects',
    'mission dialogue': 'Mission audio',
    'flock palette': 'Flock definitions',
    'flocks': 'Flock placement/simulation',
    'skies': 'Existing protected sky/environment',
    'references': 'Script/global referenced presentation dependencies',
    'scenario cluster data': 'Cluster presentation/acoustics data',
    'airprobes': 'Source lighting probes',
    'cubemaps': 'Source environment reflections',
}


def specialized(xml, inventory, native_api=None):
    counts=inventory['source_section_counts']
    selected={name for name in SPECIALIZED if counts.get(name,0)}
    # Decorator resource payloads can exceed the small authoring XML reader's
    # budget. Stream headers/references only; never parse or copy opaque data.
    evidence={name:dict(references=set(),nested=Counter()) for name in selected}
    active=None
    with open(xml,'rb') as stream:
        for line in stream:
            top=re.match(rb'    <(?:block|field|struct|array) name="([^"]*)"',line)
            if top:
                name=top[1].decode('utf-8')
                active=name if name in selected else None
            if active is None:continue
            reference=re.match(rb'\s+<field name="[^"]*" value="([^"]*)" type="tag reference"',line)
            if reference:
                value=html.unescape(reference[1].decode('utf-8',errors='replace'))
                if value and not value.startswith(','):evidence[active]['references'].add(value)
            nested=re.match(rb' {8,}<block name="([^"]*)" value="[^\"]*,(\d+)"',line)
            if nested:evidence[active]['nested'][nested[1].decode('utf-8')]+=int(nested[2])
    rows=[]
    for name in sorted(selected):
        references=evidence[name]['references'];nested=evidence[name]['nested']
        rows.append(dict(source_section=name,source_count=counts[name],
            source_references=sorted(set(references)),nested_block_counts=dict(sorted(nested.items())),
            concept=SPECIALIZED[name],disposition='RUNTIME_LATER',
            existing_native_api=(native_api or {}).get(name,'NOT_ESTABLISHED_BY_THIS_CENSUS'),
            separate_semantic_task=True,independent_of_object_population=True))
    presentation=[]
    for path,dependency in inventory['object_dependencies'].items():
        matches=[word for word in ('portal','ark','keyship','dreadnought','cloud','cinematic') if word in path.lower()]
        if matches:
            presentation.append(dict(source_tag=path,source_group=dependency['source_group'],
                palette_uses=dependency['source_palette_uses'],matched_name_terms=matches,
                evidence='SOURCE_PATH_CLASSIFICATION_ONLY; behavior is not inferred from the name',
                disposition='RUNTIME_LATER'))
    return dict(systems=rows,presentation_roots=presentation,
                zero_sections={name:counts.get(name,0) for name in SPECIALIZED if not counts.get(name,0)})


def regular(inventory, graph, dispositions, population_plan=None):
    roots={r['source_tag']:r for r in dispositions}
    population_plan=population_plan or dict(placements=[],deferred=[])
    result={}
    for family,group in inventory['families'].items():
        identities={p['source_tag'] for p in group['palette'] if p['source_tag']}
        placements=[r for r in population_plan['placements'] if r['family']==family]
        deferred=[r for r in population_plan['deferred'] if r['family']==family]
        counts=Counter(r['action'] for r in placements)
        reasons=Counter()
        for row in deferred:
            reason=row['reason']
            if isinstance(reason,str):reasons[reason]+=1
            else:
                for item in reason:reasons[item.get('reason',str(item)) if isinstance(item,dict) else str(item)]+=1
        nodes={n for source in identities for n in graph['roots'].get(source,{}).get('nodes',[])}
        reused={s for s in identities if roots.get(s,{}).get('status') in {'REUSED','REUSE_CANDIDATE_NATIVE_READBACK_VERIFIED'}}
        compiled={s for s in identities if roots.get(s,{}).get('status')=='NEWLY_COMPILED'}
        result[family]=dict(source_palette_count=group['source_palette_count'],source_placement_count=group['source_instance_count'],
            unique_roots=len(identities),dependency_closure_node_count=len(nodes),reused_roots=len(reused),
            newly_compiled_roots=len(compiled),deferred_roots=len(identities-reused-compiled),
            populated_placements=counts['APPEND'],updated_placements=counts['UPDATE'],unchanged_placements=counts['UNCHANGED'],
            deferred_placements=len(deferred) if family in population_plan.get('families',[]) else group['source_instance_count'],
            exact_deferred_roots=sorted(identities-reused-compiled),blocker_histogram=dict(reasons),
            disposition=scenario_ir.FAMILIES[family][2],runtime_status='NOT_TESTED')
    return result

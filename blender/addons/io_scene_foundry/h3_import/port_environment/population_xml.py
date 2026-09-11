"""Independent native Tool XML fingerprints for incremental authoring."""
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath

from . import fixtures, scenario_ir
from .model import stable_hash
from .native_placements import SUPPORTED


def canonical_element(element):
    attributes = dict(element.attrib)
    if element.tag == 'element':
        attributes.pop('name', None)  # Tool display labels are not authoring.
    return [element.tag, attributes, (element.text or '').strip(),
            [canonical_element(child) for child in element]]


def read(path):
    with open(path, 'rb') as stream:
        root = fixtures.parse(stream.read())
    blocks = {f: fixtures.block(root, f) for f in SUPPORTED}
    fingerprints = {f: [stable_hash(canonical_element(e)) for e in rows] for f, rows in blocks.items()}
    # Reach Tool uses a flat top-level marker followed by sibling elements.
    sections = []
    for child in root:
        if child.tag != 'element':
            sections.append(dict(name=child.get('name'), kind=child.tag, nodes=[]))
        if not sections:
            raise ValueError('Native XML element has no enclosing section marker')
        sections[-1]['nodes'].append(canonical_element(child))
    return dict(root_attributes=dict(root.attrib), placement_fingerprints=fingerprints, sections=sections,
                counts={f:len(rows) for f, rows in blocks.items()})


def forbidden_snapshot(snapshot, families=SUPPORTED):
    allowed = set(families) | {scenario_ir.FAMILIES[f][0] for f in families}
    allowed |= {'object names', 'device groups', 'designer zones'}
    return [row for row in snapshot['sections'] if row['name'] not in allowed]


def verify_preservation(before, after, plan):
    if before['root_attributes'] != after['root_attributes'] or len(before['sections']) != len(after['sections']):
        raise ValueError('Population changed native scenario schema')
    if forbidden_snapshot(before, plan['families']) != forbidden_snapshot(after, plan['families']):
        raise ValueError('Population modified a protected scenario section')
    updated = {(r['family'],r['target_index']) for r in plan['placements'] if r['action']=='UPDATE'}
    for family, hashes in before['placement_fingerprints'].items():
        current = after['placement_fingerprints'][family]
        if len(current) < len(hashes):
            raise ValueError('Population removed existing placements')
        for index, fingerprint in enumerate(hashes):
            if (family,index) not in updated and current[index] != fingerprint:
                raise ValueError('Population modified an unowned or unchanged placement')
    append_only = {'object names','device groups'} | {scenario_ir.FAMILIES[f][0] for f in plan['families']}
    for left, right in zip(before['sections'], after['sections']):
        if left['name'] != right['name'] or left['kind'] != right['kind']:
            raise ValueError('Population changed native schema ordering')
        if left['name'] in append_only and left['nodes'][1:] != right['nodes'][1:len(left['nodes'])]:
            raise ValueError('Population changed existing palette/name/group rows')
        if left['name']=='designer zones':
            if len(left['nodes']) != len(right['nodes']):
                raise ValueError('Population added or removed designer zones')
            from .native_placements import KINDS
            allowed={KINDS[f] for f in plan['families']}
            for old,new in zip(left['nodes'][1:],right['nodes'][1:]):
                def sections(node):
                    rows=[]
                    for child in node[3]:
                        if child[0]!='element':rows.append([child[1].get('name'),[]])
                        rows[-1][1].append(child)
                    return rows
                a,b=sections(old),sections(new)
                if len(a)!=len(b):raise ValueError('Designer zone schema differs')
                for x,y in zip(a,b):
                    if x[0]!=y[0]:raise ValueError('Designer zone field ordering differs')
                    if x[0] not in allowed and x!=y:raise ValueError('Unrelated designer zone membership changed')
                    if x[0] in allowed and x[1][1:]!=y[1][1:len(x[1])]:
                        raise ValueError('Existing designer zone membership changed')


def verify_expected(before,after,plan,compiled):
    sections={r['name']:r['nodes'][1:] for r in after['sections']}
    def field(element,name):
        return next(c[1]['value'] for c in element[3] if c[0]=='field' and c[1].get('name')==name)
    for family in plan['families']:
        added=sum(r['family']==family and r['action']=='APPEND' for r in plan['placements'])
        if after['counts'][family]!=before['counts'][family]+added:
            raise ValueError('Tool XML placement count differs: '+family)
    for row in plan['placements']:
        root=compiled[row['source_tag']]['target_tag']
        label=PurePosixPath(root).stem
        palette=sections[scenario_ir.FAMILIES[row['family']][0]][row['target_palette_index']]
        placement=sections[row['family']][row['target_index']]
        if field(palette,'name')!=label or field(placement,'type')!=label:
            raise ValueError('Tool XML palette/placement reference label differs')
        if field(placement,'unique id')!=str(row['unique_id']):
            raise ValueError('Tool XML source unique ID differs')
    return dict(status='TOOL_XML_VERIFIED',placements=len(plan['placements']),counts=after['counts'],
                reference_scope='Tool XML emits labels; full tag paths verified independently through ManagedBlam')
